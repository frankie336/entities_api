from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Form
from sqlalchemy.orm import Session
from entities.dependencies import get_db
from entities.schemas.file_service import FileResponse, FileUploadRequest
from entities.services.file_service import FileService
from entities.services.logging_service import LoggingUtility

router = APIRouter()
logging_utility = LoggingUtility()


@router.post("/uploads", response_model=FileResponse, status_code=201)
def upload_file(
        file: UploadFile = File(...),
        purpose: str = Form(...),  # This extracts the string value from form data
        user_id: str = Form(...),  # This extracts the string value from form data
        db: Session = Depends(get_db)
):
    """
    Upload a file and store its metadata.
    """
    # Create a request object manually
    request = FileUploadRequest(purpose=purpose, user_id=user_id)

    logging_utility.info(f"Received file upload request: {file.filename} from user {request.user_id}")

    file_service = FileService(db)  # Initialize the service with the database session
    try:
        # Process file upload via the FileService
        file_metadata = file_service.upload_file(file, request)

        # Validate and return as Pydantic object (FileResponse)
        file_response = FileResponse.model_validate(file_metadata)
        logging_utility.info(f"File uploaded successfully: {file.filename} for user {request.user_id}")
        return file_response

    except HTTPException as e:
        # Log the HTTP error and re-raise
        logging_utility.error(f"HTTP error occurred during file upload: {str(e)}")
        raise e

    except Exception as e:
        # Catch any other exceptions, log, and return a 500 error
        logging_utility.error(f"Unexpected error during file upload: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred while uploading the file.")