import hashlib
import hmac
import os
from datetime import datetime

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Response,
                     UploadFile)
from projectdavid_common import ValidationInterface
from sqlalchemy.orm import Session

from entities_api.dependencies import get_db
from entities_api.services.file_service import FileService
from entities_api.services.logging_service import LoggingUtility

router = APIRouter()
logging_utility = LoggingUtility()


@router.post(
    "/uploads", response_model=ValidationInterface.FileResponse, status_code=201
)
def upload_file(
    file: UploadFile = File(...),
    purpose: str = Form(...),  # This extracts the string value from form data
    user_id: str = Form(...),  # This extracts the string value from form data
    db: Session = Depends(get_db),
):
    """
    Upload a file and store its metadata.
    """
    # Create a request object manually
    request = ValidationInterface.FileUploadRequest(purpose=purpose, user_id=user_id)

    logging_utility.info(
        f"Received file upload request: {file.filename} from user {request.user_id}"
    )

    file_service = FileService(db)  # Initialize the service with the database session
    try:
        # Process file upload via the FileService
        file_metadata = file_service.upload_file(file, request)

        # Validate and return as Pydantic object (FileResponse)
        file_response = ValidationInterface.FileResponse.model_validate(file_metadata)
        logging_utility.info(
            f"File uploaded successfully: {file.filename} for user {request.user_id}"
        )
        return file_response

    except HTTPException as e:
        # Log the HTTP error and re-raise
        logging_utility.error(f"HTTP error occurred during file upload: {str(e)}")
        raise e

    except Exception as e:
        # Catch any other exceptions, log, and return a 500 error
        logging_utility.error(f"Unexpected error during file upload: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while uploading the file.",
        )


@router.get(
    "/uploads/{file_id}",
    response_model=ValidationInterface.FileResponse,
    status_code=200,
)
def get_file_by_id(file_id: str, db: Session = Depends(get_db)):
    """
    Retrieve file metadata by ID.
    """
    logging_utility.info(f"Received request to retrieve file with ID: {file_id}")

    file_service = FileService(db)  # Initialize the service with the database session
    try:
        # Retrieve file metadata via the FileService
        file_metadata = file_service.get_file_by_id(file_id)

        if not file_metadata:
            logging_utility.warning(f"File with ID {file_id} not found")
            raise HTTPException(
                status_code=404, detail=f"File with ID {file_id} not found"
            )

        # Validate and return as Pydantic object (FileResponse)
        file_response = ValidationInterface.FileResponse.model_validate(file_metadata)
        logging_utility.info(f"File metadata retrieved successfully for ID: {file_id}")
        return file_response

    except HTTPException as e:
        # Log the HTTP error and re-raise
        logging_utility.error(f"HTTP error occurred during file retrieval: {str(e)}")
        raise e

    except Exception as e:
        # Catch any other exceptions, log, and return a 500 error
        logging_utility.error(f"Unexpected error during file retrieval: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while retrieving the file metadata.",
        )


@router.get("/uploads/{file_id}/object", response_class=Response)
def download_file_as_object(file_id: str, db: Session = Depends(get_db)):
    """
    Retrieve file content as a streamed file-like object.
    """
    file_service = FileService(db)
    try:
        # Get the file as a BytesIO stream
        file_obj = file_service.get_file_as_object(file_id)
        # You may set an appropriate media type if available; defaulting to octet-stream.
        return Response(content=file_obj.read(), media_type="application/octet-stream")
    except HTTPException as e:
        logging_utility.error(f"HTTP error in download_file_as_object: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"Unexpected error in download_file_as_object: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Unexpected error retrieving file object."
        )


@router.get("/uploads/{file_id}/signed-url", response_model=dict)
def get_signed_url(file_id: str, db: Session = Depends(get_db)):
    """
    Generate a signed URL for downloading the file.
    """
    file_service = FileService(db)
    try:
        signed_url = file_service.get_file_as_signed_url(file_id)
        return {"signed_url": signed_url}
    except HTTPException as e:
        logging_utility.error(f"HTTP error in get_signed_url: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"Unexpected error in get_signed_url: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Unexpected error generating signed URL."
        )


@router.get("/uploads/{file_id}/base64", response_model=dict)
def get_file_as_base64(file_id: str, db: Session = Depends(get_db)):
    """
    Retrieve the file content as a BASE64-encoded string.
    """
    file_service = FileService(db)
    try:
        b64_str = file_service.get_file_as_base64(file_id)
        return {"base64": b64_str}
    except HTTPException as e:
        logging_utility.error(f"HTTP error in get_file_as_base64: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"Unexpected error in get_file_as_base64: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Unexpected error retrieving file as BASE64."
        )


@router.delete("/uploads/{file_id}", response_model=dict)
def delete_file(file_id: str, db: Session = Depends(get_db)):
    """
    Delete a file by its ID along with all its storage locations.
    """
    file_service = FileService(db)
    try:
        success = file_service.delete_file_by_id(file_id)
        if not success:
            raise HTTPException(
                status_code=404, detail=f"File with ID {file_id} not found"
            )
        return {"deleted": True}
    except HTTPException as e:
        logging_utility.error(f"HTTP error in delete_file: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"Unexpected error in delete_file: {str(e)}")
        raise HTTPException(status_code=500, detail="Unexpected error deleting file.")


@router.get("/files/download", response_class=Response)
def download_file_via_signed_url(
    file_id: str, expires: int, signature: str, db: Session = Depends(get_db)
):
    """
    Download a file using a signed URL (validates signature and expiration).
    """
    file_service = FileService(db)

    try:
        # Validate signature
        secret_key = os.getenv("SIGNED_URL_SECRET", "default_secret_key")
        data = f"{file_id}:{expires}"
        expected_signature = hmac.new(
            key=secret_key.encode(), msg=data.encode(), digestmod=hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(signature, expected_signature):
            raise HTTPException(status_code=403, detail="Invalid signature")

        # Check expiration
        current_timestamp = int(datetime.utcnow().timestamp())
        if current_timestamp > expires:
            raise HTTPException(status_code=410, detail="URL has expired")

        # Retrieve and return the file
        file_obj = file_service.get_file_as_object(file_id)
        return Response(
            content=file_obj.read(),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename={file_id}"},
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        logging_utility.error(f"Download error: {str(e)}")
        raise HTTPException(status_code=500, detail="File download failed")
