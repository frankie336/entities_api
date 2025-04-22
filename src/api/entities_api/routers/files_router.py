#!src/api/entities_api/routers/files_router.py
import hashlib
import hmac
import os
from datetime import datetime
from urllib.parse import urlencode

from dotenv import load_dotenv
from fastapi import APIRouter, Depends
from fastapi import File as FastApiFile
from fastapi import Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from projectdavid_common.schemas.file_service import (FileDeleteResponse,
                                                      FileResponse)
from projectdavid_common.utilities.logging_service import LoggingUtility
from sqlalchemy.orm import Session

from entities_api.dependencies import get_api_key, get_db
from entities_api.models.models import ApiKey as ApiKeyModel
from entities_api.models.models import File as FileModel
from entities_api.services.file_service import FileService

# --- Initialization ---
router = APIRouter(prefix="/v1", tags=["Files"])
load_dotenv()
logging_utility = LoggingUtility()


# === UPLOAD FILE ENDPOINT ===
@router.post(
    "/uploads",
    response_model=None,  # Disable response model validation
    status_code=status.HTTP_201_CREATED,
    summary="Upload a File",
    description="Uploads a file and associates it with the authenticated user.",
)
def upload_file_endpoint(
    purpose: str = Form(...),
    file: UploadFile = FastApiFile(...),
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    user_id = auth_key.user_id
    logging_utility.info(
        f"User '{user_id}' - Received request to upload file '{file.filename}' with purpose '{purpose}'"
    )

    class UploadRequestData:
        def __init__(self, purpose: str, user_id: str):
            self.purpose = purpose
            self.user_id = user_id

    try:
        request_data = UploadRequestData(purpose=purpose, user_id=user_id)
        file_service = FileService(db)
        created_file_model = file_service.upload_file(file=file, request=request_data)

        return {
            "id": created_file_model.id,
            "object": "file",
            "bytes": created_file_model.bytes,
            "created_at": int(created_file_model.created_at.timestamp()),
            "filename": created_file_model.filename,
            "purpose": created_file_model.purpose,
        }

    except HTTPException as e:
        logging_utility.warning(
            f"Upload failed for user '{user_id}', file '{file.filename}': {e.detail}"
        )
        raise e
    except Exception as e:
        logging_utility.error(
            f"Unexpected error uploading file '{file.filename}' for user '{user_id}': {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal server error occurred during file upload.",
        )


# === RETRIEVE METADATA ENDPOINT ===
@router.get(
    "/files/{file_id}",
    response_model=FileResponse,
    summary="Retrieve File Metadata",
    description="Retrieves the metadata for a specific file.",
)
def retrieve_file_metadata(
    file_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    user_id = auth_key.user_id
    logging_utility.info(f"User '{user_id}' - Retrieving metadata for file: {file_id}")
    try:
        file_service = FileService(db)
        file_data = file_service.get_file_by_id(file_id)
        if not file_data:
            raise HTTPException(status_code=404, detail="File not found.")
        return FileResponse.model_validate(file_data)
    except Exception as e:
        logging_utility.error(f"Metadata error for file {file_id}: {str(e)}")
        raise HTTPException(500, "Failed to retrieve file metadata.")


# === DELETE FILE ENDPOINT ===
@router.delete(
    "/files/{file_id}",
    response_model=FileDeleteResponse,
    summary="Delete a File",
    description="Deletes a file and its storage records.",
)
def delete_file_endpoint(
    file_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    user_id = auth_key.user_id
    logging_utility.info(f"User '{user_id}' - Requesting deletion of file: {file_id}")
    try:
        file_service = FileService(db)
        if not file_service.delete_file_by_id(file_id):
            raise HTTPException(status_code=404, detail="File not found.")
        return FileDeleteResponse(id=file_id, object="file", deleted=True)
    except Exception as e:
        logging_utility.error(f"Delete error for file {file_id}: {str(e)}")
        raise HTTPException(500, "Failed to delete file.")


# --- Signature Helper ---
def verify_signature(
    file_id: str, expires: int, signature: str, use_real_filename: bool = False
) -> bool:
    secret_key = os.getenv("SIGNED_URL_SECRET", "default_secret_key")
    data = f"{file_id}:{expires}:{str(use_real_filename).lower()}"
    computed = hmac.new(secret_key.encode(), data.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, signature)


# === DOWNLOAD FILE ENDPOINT ===
@router.get("/files/download", response_class=StreamingResponse)
def download_file(
    file_id: str,
    expires: int,
    signature: str,
    use_real_filename: bool = Query(False),
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    if datetime.utcnow().timestamp() > expires:
        raise HTTPException(400, "Signed URL has expired")
    if not verify_signature(file_id, expires, signature, use_real_filename):
        raise HTTPException(403, "Invalid signature")

    try:
        file_service = FileService(db)
        file_stream, filename, mime_type = file_service.get_file_with_metadata(file_id)
        disposition = (
            "inline"
            if mime_type.startswith(("image/", "text/"))
            or mime_type == "application/pdf"
            else "attachment"
        )
        name = filename if use_real_filename else file_id

        return StreamingResponse(
            file_stream,
            media_type=mime_type,
            headers={
                "Content-Disposition": f'{disposition}; filename="{name}"',
                "X-Content-Type-Options": "nosniff",
            },
        )
    except Exception as e:
        logging_utility.error(f"Download error for file {file_id}: {str(e)}")
        raise HTTPException(500, "Failed to process file download.")


# === SIGNED URL GENERATION ===
@router.get("/files/{file_id}/signed-url")
def generate_signed_url(
    file_id: str,
    expires_in: int = Query(600),
    use_real_filename: bool = Query(False),
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    file_record = db.query(FileModel).filter(FileModel.id == file_id).first()
    if not file_record:
        raise HTTPException(404, "File not found")

    expires = int(datetime.utcnow().timestamp() + expires_in)
    data = f"{file_id}:{expires}:{str(use_real_filename).lower()}"
    signature = hmac.new(
        os.getenv("SIGNED_URL_SECRET", "default_secret_key").encode(),
        data.encode(),
        hashlib.sha256,
    ).hexdigest()
    base_url = os.getenv("BASE_URL", "http://localhost:9000").rstrip("/")
    url = f"{base_url}/v1/files/download?" + urlencode(
        {
            "file_id": file_id,
            "expires": expires,
            "signature": signature,
            "use_real_filename": use_real_filename,
        }
    )
    return {"signed_url": url}


# === BASE64 ENCODING ENDPOINT ===
@router.get("/files/{file_id}/base64")
def get_file_as_base64(
    file_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    try:
        file_service = FileService(db)
        base64_data = file_service.get_file_as_base64(file_id)
        return {"file_id": file_id, "base64": base64_data}
    except Exception as e:
        logging_utility.error(f"Base64 encoding error for file {file_id}: {str(e)}")
        raise HTTPException(500, "Failed to retrieve BASE64 content.")
