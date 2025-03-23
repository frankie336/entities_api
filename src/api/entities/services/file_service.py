import os
import mimetypes
from datetime import datetime
from fastapi import HTTPException
from sqlalchemy.orm import Session
from entities.models.models import File, User, FileStorage
from entities.utils.samba_client import SambaClient
from entities.constants.platform import SUPPORTED_MIME_TYPES
from entities.services.identifier_service import IdentifierService
from entities.services.logging_service import LoggingUtility


logging_utility = LoggingUtility()

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
            self.db.flush()  # Flush to generate the ID without committing transaction

            # Create storage location record
            file_storage = FileStorage(
                file_id=file_metadata.id,
                storage_system="samba",
                storage_path=file.filename,  # Store the path relative to share root
                is_primary=True,
                created_at=int(datetime.now().timestamp())
            )

            # Add storage location to database
            self.db.add(file_storage)
            self.db.commit()
            self.db.refresh(file_metadata)

            # Clean up the temporary file
            os.remove(temp_file_path)

            return file_metadata

        except Exception as e:
            self.db.rollback()
            logging_utility.error(f"Error uploading file: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)}")

        finally:
            file.file.close()

    def delete_file_by_id(self, file_id: str) -> bool:
        """
        Delete a file by ID and all its storage locations.

        Args:
            file_id: The ID of the file to delete

        Returns:
            bool: True if the file was deleted, False if not found
        """
        try:
            # Query the database for the file record
            file_record = self.db.query(File).filter(File.id == file_id).first()

            if not file_record:
                logging_utility.warning(f"File with ID {file_id} not found in database")
                return False

            # Query for storage locations
            storage_locations = self.db.query(FileStorage).filter(FileStorage.file_id == file_id).all()

            # Process each storage location
            for storage_location in storage_locations:
                if storage_location.storage_system == "samba":
                    try:
                        # Delete from Samba
                        self.samba_client.delete_file(storage_location.storage_path)
                        logging_utility.info(f"File deleted from Samba: {storage_location.storage_path}")
                    except Exception as e:
                        # Log but continue with deletion
                        logging_utility.error(f"Failed to delete file from Samba: {str(e)}")
                else:
                    logging_utility.warning(f"Unsupported storage system: {storage_location.storage_system}")

            # Delete the file record (will cascade and delete storage locations)
            self.db.delete(file_record)
            self.db.commit()

            logging_utility.info(f"File with ID {file_id} and its storage locations deleted from database")
            return True

        except Exception as e:
            self.db.rollback()
            logging_utility.error(f"Error deleting file with ID {file_id}: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to delete file: {str(e)}")


    def get_file_by_id(self, file_id: str) -> dict:
        """
        Retrieve file metadata by ID.

        Args:
            file_id: The ID of the file to retrieve

        Returns:
            dict: File metadata dictionary

        Raises:
            HTTPException: If file not found or other errors occur
        """
        try:
            # Query the database for the file record
            file_record = self.db.query(File).filter(File.id == file_id).first()

            if not file_record:
                return None

            # Convert database model to dictionary
            return {
                "id": file_record.id,
                "object": "file",
                "bytes": file_record.bytes,
                "created_at": int(file_record.created_at.timestamp()),
                "filename": file_record.filename,
                "purpose": file_record.purpose,
            }

        except Exception as e:
            # Log the error and re-raise
            logging_utility.error(f"Error retrieving file with ID {file_id}: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to retrieve file: {str(e)}")