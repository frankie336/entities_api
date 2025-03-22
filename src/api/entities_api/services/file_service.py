import os
from datetime import datetime

from entities_api.models.models import File, User
from entities_api.utils.samba_client import SambaClient


samba_client = SambaClient(os.getenv("SMBCLIENT_SERVER"), os.getenv("SMBCLIENT_SHARE"),
                           os.getenv("SMBCLIENT_USERNAME"), os.getenv("SMBCLIENT_PASSWORD"))

class FileService:
    @staticmethod
    def upload_file(file, request, db):
        """
        Handles file upload logic, including saving metadata in the database.
        """
        # Validate user
        user = db.query(User).filter(User.id == request.user_id).first()
        if not user:
            raise ValueError("User not found")

        # Generate a unique file ID
        file_id = f"file-{datetime.now().timestamp()}"

        # Upload file to Samba server
        try:
            samba_client.upload_file(file.file, file.filename)

            # Create file metadata
            file_metadata = File(
                id=file_id,
                object="file",
                bytes=os.path.getsize(file.file.name),
                created_at=int(datetime.now().timestamp()),
                expires_at=None,
                filename=file.filename,
                purpose=request.purpose,
                user_id=request.user_id
            )

            # Save metadata to the database
            db.add(file_metadata)
            db.commit()
            db.refresh(file_metadata)

            return file_metadata
        except Exception as e:
            db.rollback()
            raise RuntimeError(f"Failed to upload file: {str(e)}")
        finally:
            file.file.close()
