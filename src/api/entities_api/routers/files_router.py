# entities_api/routers/uploads.py
import os
import hashlib
import hmac
from datetime import datetime
from urllib.parse import urlencode

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Query, status, Form, UploadFile, File as FastApiFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common import ValidationInterface
from entities_api.dependencies import get_api_key, get_db
from entities_api.models.models import ApiKey as ApiKeyModel
from entities_api.services import file_service
from entities_api.services.file_service import FileService

# --- Initialization ---
router = APIRouter()
logging_utility = LoggingUtility()
load_dotenv()
validator = ValidationInterface()

# === UPLOAD ENDPOINT ===
@router.post(
    "/uploads",
    response_model=validator.FileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a File",
    description="Uploads a file with purpose and associates it with the authenticated user.",
)
def upload_file_endpoint(
    purpose: str = Form(...),
    file: UploadFile = FastApiFile(...),
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
    file_service: FileService = Depends(FileService),
):
    user_id = auth_key.user_id
    logging_utility.info(
        f"User '{user_id}' - Received request to upload file '{file.filename}' with purpose '{purpose}'"
    )

    # Build request data for service
    class UploadRequestData:
        def __init__(self, purpose: str, user_id: str):
            self.purpose = purpose
            self.user_id = user_id

    request_data = UploadRequestData(purpose=purpose, user_id=user_id)

    try:
        created_file = file_service.upload_file(file=file, request=request_data)
        response_data = validator.FileResponse(
            id=created_file.id,
            object="file",
            bytes=created_file.bytes,
            created_at=int(created_file.created_at.timestamp()),
            filename=created_file.filename,
            purpose=created_file.purpose,
        )
        logging_utility.info(
            f"File '{response_data.filename}' uploaded successfully with ID: {response_data.id} by user '{user_id}'"
        )
        return response_data

    except HTTPException as e:
        logging_utility.warning(
            f"Upload failed for user '{user_id}', file '{file.filename}': {e.detail}"
        )
        raise e
    except Exception as e:
        logging_utility.error(
            f"Unexpected error uploading file '{file.filename}' for user '{user_id}': {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal server error occurred during file upload.",
        )

# === RETRIEVE METADATA ENDPOINT ===
@router.get(
    "/files/{file_id}",
    response_model=validator.FileResponse,
    summary="Retrieve File Metadata",
    description="Retrieves the metadata for a specific file.",
)
def retrieve_file_metadata(
    file_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
    file_service: FileService = Depends(FileService),
):
    user_id = auth_key.user_id
    logging_utility.info(f"User '{user_id}' - Retrieving metadata for file: {file_id}")
    try:
        file_data = file_service.get_file_by_id(file_id)
        if not file_data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")
        response = validator.FileResponse.model_validate(file_data)
        logging_utility.info(f"Metadata retrieved for file ID: {file_id}")
        return response
    except HTTPException:
        raise
    except Exception as e:
        logging_utility.error(
            f"Error retrieving metadata for file '{file_id}' by user '{user_id}': {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal server error occurred retrieving file metadata.",
        )

# === DELETE FILE ENDPOINT ===
@router.delete(
    "/files/{file_id}",
    status_code=status.HTTP_200_OK,
    response_model=validator.FileDeleteResponse,
    summary="Delete a File",
    description="Deletes a file and its associated storage records.",
)
def delete_file_endpoint(
    file_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
    file_service: FileService = Depends(FileService),
):
    user_id = auth_key.user_id
    logging_utility.info(f"User '{user_id}' - Requesting deletion of file: {file_id}")
    try:
        deleted = file_service.delete_file_by_id(file_id)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found for deletion.")
        logging_utility.info(f"File ID: {file_id} deleted successfully by user '{user_id}'")
        return validator.FileDeleteResponse(id=file_id, object="file", deleted=True)
    except HTTPException:
        raise
    except Exception as e:
        logging_utility.error(
            f"Unexpected error deleting file '{file_id}' by user '{user_id}': {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal server error occurred during file deletion.",
        )

# === DOWNLOAD ENDPOINT ===
@router.get("/v1/files/download", response_class=StreamingResponse)
def download_file(
    file_id: str,
    expires: int,
    signature: str,
    use_real_filename: bool = Query(False),
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(f"User '{auth_key.user_id}' - Downloading file: {file_id}")
    if datetime.utcnow().timestamp() > expires:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Signed URL has expired")
    if not file_service.verify_signature(file_id, expires, signature, use_real_filename):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid signature")
    file_stream, filename, mime_type = file_service.get_file_with_metadata(db, file_id)
    is_inline = mime_type.startswith(("image/", "text/")) or mime_type == "application/pdf"
    disposition = "inline" if is_inline else "attachment"
    headers = {
        "Content-Disposition": f'{disposition}; filename="{filename if use_real_filename else file_id}"',
        "X-Content-Type-Options": "nosniff",
    }
    return StreamingResponse(file_stream, media_type=mime_type, headers=headers)

# === SIGNED URL ENDPOINT ===
@router.get("/v1/uploads/{file_id}/signed-url")
def generate_signed_url(
    file_id: str,
    expires_in: int = Query(600),
    use_real_filename: bool = Query(False),
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(
        f"User '{auth_key.user_id}' - Generating signed URL for file: {file_id} with TTL: {expires_in}s"
    )
    signed_url = file_service.get_file_as_signed_url(db, file_id, expires_in, use_real_filename)
    return {"signed_url": signed_url}


