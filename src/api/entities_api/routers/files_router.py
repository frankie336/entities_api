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
from fastapi.responses import (JSONResponse,
                               StreamingResponse)
from projectdavid_common import \
    ValidationInterface  # Assuming FileResponse is here
from projectdavid_common.utilities.logging_service import LoggingUtility
from sqlalchemy.orm import Session

from entities_api.dependencies import get_api_key, get_db
from entities_api.models.models import ApiKey as ApiKeyModel
from entities_api.models.models import \
    File as FileModel  # Renamed File model import
from entities_api.services.file_service import FileService

# --- Initialization ---
router = APIRouter(
    prefix="/v1",  # Add prefix for consistency if not already on main app
    tags=["Files"],  # Add tags for Swagger UI organization
)
logging_utility = LoggingUtility()
load_dotenv()
validator = ValidationInterface()  # Instantiate validator if FileResponse is part of it


# === NEW UPLOAD ENDPOINT ===
@router.post(
    "/uploads",  # Path relative to router prefix, becomes /v1/uploads
    response_model=validator.FileResponse,  # Use the response model from common interface
    status_code=status.HTTP_201_CREATED,
    summary="Upload a File",
    description="Uploads a file with purpose and associates it with the authenticated user.",
)
def upload_file_endpoint(  # Changed to sync as FileService is sync
    purpose: str = Form(...),
    # user_id: str = Form(...), # Use authenticated user_id instead for security
    file: UploadFile = FastApiFile(...),  # Use UploadFile type hint
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
    file_service: FileService = Depends(
        FileService
    ),  # Dependency injection for FileService
):
    """
    Handles file uploads via multipart/form-data.
    - **purpose**: The purpose of the file (e.g., 'assistants').
    - **file**: The file to upload.
    """
    user_id = auth_key.user_id  # Use the authenticated user's ID
    logging_utility.info(
        f"User '{user_id}' - Received request to upload file '{file.filename}' with purpose '{purpose}'"
    )

    # The FileService expects a 'request' object with purpose and user_id
    # Create a simple structure to pass this info
    class UploadRequestData:
        def __init__(self, purpose: str, user_id: str):
            self.purpose = purpose
            self.user_id = user_id

    request_data = UploadRequestData(purpose=purpose, user_id=user_id)

    try:
        # Instantiate service within the endpoint or use dependency injection
        # file_service = FileService(db) # Option 1: Instantiate here
        # Option 2 (preferred): Add FileService as a dependency (see updated signature)

        # Call the service method - NOTE: FileService.upload_file is currently SYNCHRONOUS
        # If FileService becomes async later, this endpoint should be async and use await
        created_file_model = file_service.upload_file(file=file, request=request_data)

        # Convert the DB model response to the Pydantic response model
        # Ensure fields match ValidationInterface.FileResponse
        response_data = validator.FileResponse(
            id=created_file_model.id,
            object="file",  # Or created_file_model.object if it exists
            bytes=created_file_model.bytes,
            created_at=int(created_file_model.created_at.timestamp()),
            filename=created_file_model.filename,
            purpose=created_file_model.purpose,
            # Add status if needed by FileResponse, e.g., status="uploaded"
        )
        logging_utility.info(
            f"File '{response_data.filename}' uploaded successfully with ID: {response_data.id} by user '{user_id}'"
        )
        return response_data

    except HTTPException as e:
        # Re-raise specific HTTP exceptions from the service (like validation)
        logging_utility.warning(
            f"Upload failed for user '{user_id}', file '{file.filename}': {e.detail}"
        )
        raise e
    except Exception as e:
        # Catch broader errors during upload process
        logging_utility.error(
            f"Unexpected error uploading file '{file.filename}' for user '{user_id}': {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An internal server error occurred during file upload.",
        )


# === END NEW UPLOAD ENDPOINT ===


# === NEW RETRIEVE METADATA ENDPOINT ===
@router.get(
    "/files/{file_id}",  # Use /files/ path for consistency with OpenAI API
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
        # Using get_file_by_id which returns a dict matching OpenAI format
        file_data = file_service.get_file_by_id(file_id)
        if not file_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"File with ID '{file_id}' not found.",
            )

        # Validate/convert dict to the Pydantic model
        response_data = validator.FileResponse.model_validate(file_data)
        logging_utility.info(f"Metadata retrieved for file ID: {file_id}")
        return response_data

    except HTTPException as e:
        raise e
    except Exception as e:
        logging_utility.error(
            f"Error retrieving metadata for file '{file_id}' by user '{user_id}': {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An internal server error occurred retrieving file metadata.",
        )


# === END NEW RETRIEVE METADATA ENDPOINT ===


# === NEW DELETE FILE ENDPOINT ===
@router.delete(
    "/files/{file_id}",  # Use /files/ path
    status_code=status.HTTP_200_OK,  # Return 200 OK with deletion status
    response_model=validator.FileDeleteResponse,  # Define a simple response model
    summary="Delete a File",
    description="Deletes a file and its associated storage records.",
)
def delete_file_endpoint(
    file_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
    file_service: FileService = Depends(FileService),
):
    """
    Deletes a file by its ID.
    """
    user_id = auth_key.user_id
    logging_utility.info(f"User '{user_id}' - Requesting deletion of file: {file_id}")

    try:
        deleted = file_service.delete_file_by_id(file_id=file_id)

        if not deleted:
            # delete_file_by_id might return False if file not found initially
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"File with ID '{file_id}' not found for deletion.",
            )

        logging_utility.info(
            f"File ID: {file_id} deleted successfully by user '{user_id}'."
        )
        # Return OpenAI-like deletion confirmation
        return validator.FileDeleteResponse(id=file_id, object="file", deleted=True)

    except HTTPException as e:
        # Handle potential 500 errors raised during delete process in service
        if e.status_code == 500:
            logging_utility.error(
                f"Deletion failed for file '{file_id}' requested by user '{user_id}': {e.detail}",
                exc_info=True,
            )
        raise e  # Re-raise original exception
    except Exception as e:
        logging_utility.error(
            f"Unexpected error deleting file '{file_id}' by user '{user_id}': {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An internal server error occurred during file deletion.",
        )


# === END NEW DELETE FILE ENDPOINT ===


# --- Signature Verification ---
def verify_signature(
    file_id: str, expires: int, signature: str, use_real_filename: bool = False
) -> bool:
    secret_key = os.getenv("SIGNED_URL_SECRET", "default_secret_key")
    # Ensure consistent data format for signature generation/verification
    data_parts = [file_id, str(expires), str(use_real_filename).lower()]
    data = ":".join(data_parts)
    computed_signature = hmac.new(
        secret_key.encode(), data.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(computed_signature, signature)


# --- Download Endpoint ---
# No changes needed here, assuming it works
@router.get(
    "/files/download", response_class=StreamingResponse
)  # Keep path relative to /v1
def download_file(
    file_id: str,
    expires: int,
    signature: str,
    use_real_filename: bool = Query(False),
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
    file_service: FileService = Depends(FileService),  # Inject service
):
    # ... (rest of the download logic remains the same)
    logging_utility.info(
        f"User '{auth_key.user_id}' - Requesting download for file: {file_id}"
    )
    if datetime.utcnow().timestamp() > expires:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Signed URL has expired"
        )

    # Verify signature using the same logic as generation
    if not verify_signature(file_id, expires, signature, use_real_filename):
        logging_utility.warning(
            f"Invalid download signature for file {file_id} by user '{auth_key.user_id}'."
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid signature"
        )

    # file_service = FileService(db) # Use injected service
    try:
        file_stream, filename, mime_type = file_service.get_file_with_metadata(file_id)

        is_inline = (
            mime_type.startswith(("image/", "text/")) or mime_type == "application/pdf"
        )
        disposition_type = "inline" if is_inline else "attachment"

        # Use the actual filename from DB if use_real_filename is true
        content_disposition_filename = filename if use_real_filename else file_id

        headers = {
            "Content-Disposition": f'{disposition_type}; filename="{content_disposition_filename}"',
            "X-Content-Type-Options": "nosniff",  # Security header
            # Add Cache-Control if appropriate, e.g., Cache-Control: private, max-age=0, must-revalidate
        }
        logging_utility.info(
            f"Serving file {file_id} ({filename}) with mime-type {mime_type} to user '{auth_key.user_id}'."
        )
        return StreamingResponse(file_stream, media_type=mime_type, headers=headers)

    except HTTPException as e:
        raise e  # Re-raise 404 etc. from get_file_with_metadata
    except Exception as e:
        logging_utility.error(
            f"Error serving download for file '{file_id}' by user '{auth_key.user_id}': {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process file download.",
        )


# --- Signed URL Endpoint ---
# Changed path slightly for consistency
@router.get("/files/{file_id}/signed-url")
def generate_signed_url(
    file_id: str,
    expires_in: int = Query(600, description="Validity duration in seconds"),
    use_real_filename: bool = Query(
        False, description="Include the original filename in the download URL"
    ),
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):

    logging_utility.info(
        f"User '{auth_key.user_id}' - Generating signed URL for file: {file_id} with TTL: {expires_in}s"
    )

    file_record = db.query(FileModel).filter(FileModel.id == file_id).first()
    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found"
        )

    secret_key = os.getenv("SIGNED_URL_SECRET", "default_secret_key")
    base_url = os.getenv("BASE_URL", "http://localhost:9000").rstrip(
        "/"
    )  # Ensure no trailing slash
    expires = int((datetime.utcnow().timestamp()) + expires_in)

    # Ensure data format matches verification logic
    data_parts = [file_id, str(expires), str(use_real_filename).lower()]
    data = ":".join(data_parts)
    signature = hmac.new(secret_key.encode(), data.encode(), hashlib.sha256).hexdigest()

    query_params = {
        "file_id": file_id,
        "expires": expires,
        "signature": signature,
        "use_real_filename": use_real_filename,  # Pass boolean directly, urlencode handles conversion
    }
    # Point to the download endpoint within this router
    signed_url = f"{base_url}{router.prefix}/files/download?{urlencode(query_params)}"
    logging_utility.info(f"Generated signed URL for file {file_id}: {signed_url}")
    return {"signed_url": signed_url}


# --- Base64 Endpoint ---
# Changed path slightly for consistency
@router.get("/files/{file_id}/base64")
def get_file_as_base64(
    file_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
    file_service: FileService = Depends(FileService),  # Inject service
):
    # ... (rest of the base64 logic)
    logging_utility.info(
        f"User '{auth_key.user_id}' - Retrieving file as BASE64: {file_id}"
    )
    # file_service = FileService(db) # Use injected service

    try:
        base64_content = file_service.get_file_as_base64(file_id)
        logging_utility.info(
            f"BASE64 content generated successfully for file {file_id}."
        )
        return {"file_id": file_id, "base64": base64_content}
    except HTTPException as e:
        raise e  # Re-raise 404 etc.
    except Exception as e:
        logging_utility.error(
            f"Failed to return BASE64 content for file {file_id} by user '{auth_key.user_id}': {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve BASE64 content",
        )
