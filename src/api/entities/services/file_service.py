import os
import mimetypes
from datetime import datetime
from fastapi import HTTPException
from sqlalchemy.orm import Session
from entities.models.models import File, User
from entities.utils.samba_client import SambaClient
from entities.constants.platform import SUPPORTED_MIME_TYPES
from entities.services.identifier_service import IdentifierService


class FileService:
    def __init__(self, db: Session):
        """
        Initialize FileService with a database session.
        """
        self.identifier_service = IdentifierService()
        self.db = db
        self.samba_client = SambaClient(
            os.getenv("SMBCLIENT_SERVER"),
            os.getenv("SMBCLIENT_SHARE"),
            os.getenv("SMBCLIENT_USERNAME"),
            os.getenv("SMBCLIENT_PASSWORD"),
        )

    def validate_file_type(self, filename: str, content_type: str = None) -> str:
        """
        Validates if the file type is supported based on extension and optional content_type.
        Returns the validated MIME type or raises an HTTPException if not supported.
        """
        _, ext = os.path.splitext(filename.lower())

        # Check if extension is supported
        if ext not in SUPPORTED_MIME_TYPES:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}. Supported types: {SUPPORTED_MIME_TYPES.keys()}")

        # Determine MIME type from extension
        expected_mime = SUPPORTED_MIME_TYPES[ext]

        # If content_type is provided, verify it matches the expected MIME type
        if content_type and content_type != expected_mime:
            raise HTTPException(
                status_code=400,
                detail=f"Content type mismatch: expected {expected_mime}, got {content_type}",
            )

        return expected_mime

    def validate_user(self, user_id: str) -> User:
        """
        Validates that a user exists in the database.
        """
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user

    def upload_file(self, file, request) -> File:
        """
        Handles file upload logic, including validation, uploading to Samba, and saving metadata in the database.
        """
        # Validate user
        user = self.validate_user(request.user_id)

        # Validate file type
        mime_type = self.validate_file_type(file.filename, getattr(file, "content_type", None))

        try:
            # Save the uploaded file to a temporary location
            temp_file_path = f"/tmp/{file.filename}"
            with open(temp_file_path, "wb") as f:
                # Reset the file pointer to the beginning
                file.file.seek(0)
                # Copy content to the temporary file
                f.write(file.file.read())

            # Upload file to Samba using the path
            self.samba_client.upload_file(temp_file_path, file.filename)

            # Get file size
            file_size = os.path.getsize(temp_file_path)

            # Create file metadata
            file_metadata = File(
                id=self.identifier_service.generate_file_id(),
                object="file",
                bytes=file_size,  # Use the actual file size
                created_at=int(datetime.now().timestamp()),
                expires_at=None,
                filename=file.filename,
                purpose=request.purpose,
                user_id=request.user_id,
                mime_type=mime_type,  # Store validated MIME type
            )

            # Save file metadata to database
            self.db.add(file_metadata)
            self.db.commit()
            self.db.refresh(file_metadata)

            # Clean up the temporary file
            os.remove(temp_file_path)

            return file_metadata

        except Exception as e:
            self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)}")

        finally:
            file.file.close()