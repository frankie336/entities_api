import base64
import hashlib
import hmac
import io
import os
from datetime import datetime, timedelta
from typing import Tuple
from urllib.parse import urlencode

from fastapi import HTTPException
from projectdavid_common import UtilsInterface, ValidationInterface
from projectdavid_common.constants.mime_types import (SUPPORTED_MIME_TYPES,
                                                      get_mime_type)
from projectdavid_common.utilities.logging_service import LoggingUtility
from sqlalchemy.orm import Session

from src.api.entities_api.models.models import File, FileStorage, User
from src.api.entities_api.utils.samba_client import SambaClient

logging_utility = LoggingUtility()
validator = ValidationInterface()


class FileService:

    def __init__(self, db: Session):
        self.identifier_service = UtilsInterface.IdentifierService()
        self.db = db
        self.samba_client = SambaClient(
            os.getenv("SMBCLIENT_SERVER"),
            os.getenv("SMBCLIENT_SHARE"),
            os.getenv("SMBCLIENT_USERNAME"),
            os.getenv("SMBCLIENT_PASSWORD"),
        )

    # ──────────────────────────────────────────────────────────────────
    # Internal ownership helper
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _assert_owner(file_record: File, user_id: str) -> None:
        """
        Raise 403 if user_id does not own this file.
        404 is deliberately NOT used here — we never confirm the file
        exists to a caller who doesn't own it.
        """
        if file_record.user_id != user_id:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to access this file.",
            )

    # ──────────────────────────────────────────────────────────────────
    # Validation helpers
    # ──────────────────────────────────────────────────────────────────

    def validate_file_type(self, filename: str, content_type: str = None) -> str:
        mime_type = get_mime_type(filename)
        if not mime_type:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {os.path.splitext(filename)[1].lower()}. "
                f"Supported types: {list(SUPPORTED_MIME_TYPES.keys())}",
            )
        if content_type and content_type != mime_type:
            raise HTTPException(
                status_code=400,
                detail=f"Content type mismatch: expected {mime_type}, got {content_type}",
            )
        return mime_type

    def validate_user(self, user_id: str) -> User:
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user

    # ──────────────────────────────────────────────────────────────────
    # Upload  (user_id always comes from the auth token in the router)
    # ──────────────────────────────────────────────────────────────────

    def upload_file(self, file, request) -> File:
        mime_type = self.validate_file_type(file.filename, getattr(file, "content_type", None))
        try:
            temp_file_path = f"/tmp/{file.filename}"
            with open(temp_file_path, "wb") as f:
                file.file.seek(0)
                f.write(file.file.read())
            file_metadata = File(
                id=self.identifier_service.generate_file_id(),
                object="file",
                bytes=os.path.getsize(temp_file_path),
                created_at=datetime.now(),
                expires_at=datetime.utcnow() + timedelta(hours=1),
                filename=file.filename,
                purpose=request.purpose,
                user_id=request.user_id,  # always auth_key.user_id, set in router
                mime_type=mime_type,
            )
            self.db.add(file_metadata)
            self.db.flush()
            unique_filename = f"{file_metadata.id}_{file.filename}"
            self.samba_client.upload_file(temp_file_path, unique_filename)
            file_storage = FileStorage(
                file_id=file_metadata.id,
                storage_system="samba",
                storage_path=unique_filename,
                is_primary=True,
                created_at=datetime.now(),
            )
            self.db.add(file_storage)
            self.db.commit()
            self.db.refresh(file_metadata)
            os.remove(temp_file_path)
            return file_metadata
        except HTTPException:
            raise
        except Exception as e:
            self.db.rollback()
            logging_utility.error(f"Error uploading file: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)}")
        finally:
            file.file.close()

    # ──────────────────────────────────────────────────────────────────
    # Delete  — ownership enforced
    # ──────────────────────────────────────────────────────────────────

    def delete_file_by_id(self, file_id: str, *, user_id: str) -> bool:
        """
        Delete a file by ID.  Raises 403 if user_id does not own the file.
        Returns False (→ 404 at router) if the file does not exist.
        """
        try:
            file_record = self.db.query(File).filter(File.id == file_id).first()
            if not file_record:
                logging_utility.warning(f"File with ID {file_id} not found in database")
                return False

            # ── Ownership check ──────────────────────────────────────
            self._assert_owner(file_record, user_id)

            storage_locations = (
                self.db.query(FileStorage).filter(FileStorage.file_id == file_id).all()
            )
            for storage_location in storage_locations:
                if storage_location.storage_system == "samba":
                    try:
                        self.samba_client.delete_file(storage_location.storage_path)
                    except Exception as e:
                        logging_utility.error(f"Failed to delete file from Samba: {str(e)}")
            self.db.delete(file_record)
            self.db.commit()
            return True
        except HTTPException:
            raise
        except Exception as e:
            self.db.rollback()
            logging_utility.error(f"Error deleting file with ID {file_id}: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to delete file: {str(e)}")

    # ──────────────────────────────────────────────────────────────────
    # Soft-delete  — ownership enforced, physical bytes preserved
    # ──────────────────────────────────────────────────────────────────
    def soft_delete_file_by_id(self, file_id: str, *, user_id: str) -> bool:
        """
        Soft-delete a file by stamping deleted_at with the current UTC epoch.
        The DB row and Samba bytes are preserved; the file becomes invisible
        to all normal queries.

        Returns False (→ 404 at router) if the file does not exist or is
        already soft-deleted.
        Raises 403 if user_id does not own the file.
        """
        try:
            file_record = (
                self.db.query(File).filter(File.id == file_id, File.deleted_at.is_(None)).first()
            )
            if not file_record:
                logging_utility.warning(
                    "File %s not found or already deleted — soft-delete aborted.", file_id
                )
                return False

            self._assert_owner(file_record, user_id)

            file_record.deleted_at = int(datetime.utcnow().timestamp())
            self.db.commit()
            logging_utility.info("File %s soft-deleted by user %s.", file_id, user_id)
            return True

        except HTTPException:
            raise
        except Exception as e:
            self.db.rollback()
            logging_utility.error("Error soft-deleting file %s: %s", file_id, str(e))
            raise HTTPException(status_code=500, detail=f"Failed to soft-delete file: {str(e)}")

    # ──────────────────────────────────────────────────────────────────
    # Retrieve metadata  — ownership enforced
    # ──────────────────────────────────────────────────────────────────

    def get_file_by_id(self, file_id: str, *, user_id: str) -> dict:
        """
        Retrieve file metadata by ID.
        Raises 403 if user_id does not own the file.
        Returns None (→ 404 at router) if the file does not exist.
        """
        try:
            file_record = self.db.query(File).filter(File.id == file_id).first()
            if not file_record:
                return None

            # ── Ownership check ──────────────────────────────────────
            self._assert_owner(file_record, user_id)

            return {
                "id": file_record.id,
                "object": "file",
                "bytes": file_record.bytes,
                "created_at": int(file_record.created_at.timestamp()),
                "filename": file_record.filename,
                "purpose": file_record.purpose,
            }
        except HTTPException:
            raise
        except Exception as e:
            logging_utility.error(f"Error retrieving file with ID {file_id}: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to retrieve file: {str(e)}")

    # ──────────────────────────────────────────────────────────────────
    # Content retrieval  — ownership enforced on all paths
    # ──────────────────────────────────────────────────────────────────

    def get_file_as_object(self, file_id: str, *, user_id: str) -> io.BytesIO:
        """
        Retrieve file content as a file-like object.
        Raises 403 if user_id does not own the file.
        """
        file_record = self.db.query(File).filter(File.id == file_id).first()
        if not file_record:
            raise HTTPException(status_code=404, detail="File not found")

        # ── Ownership check ──────────────────────────────────────────
        self._assert_owner(file_record, user_id)

        file_storage = self.db.query(FileStorage).filter(FileStorage.file_id == file_id).first()
        if not file_storage:
            raise HTTPException(status_code=404, detail="File storage record not found")
        try:
            file_bytes = self.samba_client.download_file_to_bytes(file_storage.storage_path)
            return io.BytesIO(file_bytes)
        except Exception as e:
            logging_utility.error(f"Error retrieving file object for ID {file_id}: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to retrieve file: {str(e)}")

    def get_file_as_base64(self, file_id: str, *, user_id: str) -> str:
        """
        Retrieve the file content as a BASE64-encoded string.
        Raises 403 if user_id does not own the file.
        """
        file_record = self.db.query(File).filter(File.id == file_id).first()
        if not file_record:
            raise HTTPException(status_code=404, detail="File not found")

        # ── Ownership check ──────────────────────────────────────────
        self._assert_owner(file_record, user_id)

        file_storage = self.db.query(FileStorage).filter(FileStorage.file_id == file_id).first()
        if not file_storage:
            raise HTTPException(status_code=404, detail="File storage record not found")
        try:
            file_bytes = self.samba_client.download_file_to_bytes(file_storage.storage_path)
            return base64.b64encode(file_bytes).decode("utf-8")
        except Exception as e:
            logging_utility.error(f"Error retrieving BASE64 for file ID {file_id}: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to retrieve file: {str(e)}")

    def get_file_with_metadata(self, file_id: str, *, user_id: str) -> Tuple[io.BytesIO, str, str]:
        """
        Returns (file-like-object, filename, mime_type) for download use.
        Raises 403 if user_id does not own the file.

        NOTE: called by the signed-URL download endpoint which is intentionally
        unauthenticated — pass user_id=None to bypass the ownership check in
        that specific path (signature verification already proves legitimacy).
        """
        file_obj = self.get_file_as_object(file_id, user_id=user_id)
        file_record = self.db.query(File).filter(File.id == file_id).first()
        if not file_record:
            raise HTTPException(status_code=404, detail="File metadata not found")
        filename = file_record.filename or f"{file_id}"
        mime_type = file_record.mime_type or "application/octet-stream"
        return (file_obj, filename, mime_type)

    def get_file_as_signed_url(
        self, file_id: str, *, user_id: str, expires_in: int = 3600, label: str = None
    ) -> str:
        """
        Generate a signed Markdown-safe URL.
        Raises 403 if user_id does not own the file.
        """
        file_record = self.db.query(File).filter(File.id == file_id).first()
        if not file_record:
            raise HTTPException(status_code=404, detail=f"File with ID {file_id} not found")

        # ── Ownership check ──────────────────────────────────────────
        self._assert_owner(file_record, user_id)

        secret_key = os.getenv("SIGNED_URL_SECRET", "default_secret_key")
        expiration_time = datetime.utcnow() + timedelta(seconds=expires_in)
        expiration_timestamp = int(expiration_time.timestamp())
        data = f"{file_id}:{expiration_timestamp}"
        signature = hmac.new(
            key=secret_key.encode(), msg=data.encode(), digestmod=hashlib.sha256
        ).hexdigest()
        query_params = {
            "file_id": file_id,
            "expires": expiration_timestamp,
            "signature": signature,
        }
        base_url = os.getenv("DOWNLOAD_BASE_URL", "http://localhost:9000/v1/files/download")
        signed_url = f"{base_url}?{urlencode(query_params)}"

        if label:
            return f"[{label}](<{signed_url}>)"
        return f"<{signed_url}>"
