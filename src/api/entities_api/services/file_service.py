# entities_api/services/file_service.py
import os
import io
import base64
import hashlib
import hmac
from datetime import datetime, timedelta
from typing import Tuple
from urllib.parse import urlencode

from sqlalchemy.orm import Session
from fastapi import HTTPException

from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common import UtilsInterface, ValidationInterface
from projectdavid_common.constants.mime_types import SUPPORTED_MIME_TYPES, get_mime_type
from entities_api.models.models import File, FileStorage, User
from entities_api.utils.samba_client import SambaClient

logging_utility = LoggingUtility()
validator = ValidationInterface()

class FileService:
    def __init__(self, db: Session):
        self.db = db
        self.identifier_service = UtilsInterface.IdentifierService()
        self.samba_client = SambaClient(
            os.getenv("SMBCLIENT_SERVER"),
            os.getenv("SMBCLIENT_SHARE"),
            os.getenv("SMBCLIENT_USERNAME"),
            os.getenv("SMBCLIENT_PASSWORD"),
        )

    def validate_file_type(self, filename: str, content_type: str = None) -> str:
        mime_type = get_mime_type(filename)
        if not mime_type:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {os.path.splitext(filename)[1].lower()}",
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

    def upload_file(self, file, request) -> File:
        mime_type = self.validate_file_type(
            file.filename, getattr(file, "content_type", None)
        )
        temp_path = f"/tmp/{file.filename}"
        try:
            with open(temp_path, "wb") as f:
                file.file.seek(0)
                f.write(file.file.read())

            file_meta = File(
                id=self.identifier_service.generate_file_id(),
                object="file",
                bytes=os.path.getsize(temp_path),
                created_at=datetime.now(),
                filename=file.filename,
                purpose=request.purpose,
                user_id=request.user_id,
                mime_type=mime_type,
            )
            self.db.add(file_meta)
            self.db.flush()

            unique_name = f"{file_meta.id}_{file.filename}"
            self.samba_client.upload_file(temp_path, unique_name)

            storage = FileStorage(
                file_id=file_meta.id,
                storage_system="samba",
                storage_path=unique_name,
                is_primary=True,
                created_at=datetime.now(),
            )
            self.db.add(storage)
            self.db.commit()
            self.db.refresh(file_meta)
            return file_meta
        except Exception as e:
            self.db.rollback()
            logging_utility.error(f"Error uploading file: {e}")
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            file.file.close()
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def delete_file_by_id(self, file_id: str) -> bool:
        record = self.db.query(File).filter(File.id == file_id).first()
        if not record:
            return False
        try:
            locations = self.db.query(FileStorage).filter(FileStorage.file_id == file_id).all()
            for loc in locations:
                if loc.storage_system == "samba":
                    self.samba_client.delete_file(loc.storage_path)
            self.db.delete(record)
            self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            logging_utility.error(f"Error deleting file: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    def get_file_by_id(self, file_id: str) -> dict:
        record = self.db.query(File).filter(File.id == file_id).first()
        if not record:
            return None
        return {
            "id": record.id,
            "object": "file",
            "bytes": record.bytes,
            "created_at": int(record.created_at.timestamp()),
            "filename": record.filename,
            "purpose": record.purpose,
        }

    def get_file_with_metadata(self, db: Session, file_id: str) -> Tuple[io.BytesIO, str, str]:
        record = self.db.query(File).filter(File.id == file_id).first()
        if not record:
            raise HTTPException(status_code=404, detail="File not found")
        file_obj = io.BytesIO(self.samba_client.download_file_to_bytes(
            self.db.query(FileStorage).filter(FileStorage.file_id == file_id).first().storage_path
        ))
        return file_obj, record.filename or file_id, record.mime_type or "application/octet-stream"

    def get_file_as_signed_url(self, db: Session, file_id: str, expires_in: int, use_real_filename: bool) -> str:
        record = self.db.query(File).filter(File.id == file_id).first()
        if not record:
            raise HTTPException(status_code=404, detail="File not found")
        expires = int((datetime.utcnow() + timedelta(seconds=expires_in)).timestamp())
        data = f"{file_id}:{expires}:{use_real_filename}"
        sig = hmac.new(os.getenv("SIGNED_URL_SECRET", "" ).encode(), data.encode(), hashlib.sha256).hexdigest()
        params = urlencode({
            "file_id": file_id,
            "expires": expires,
            "signature": sig,
            "use_real_filename": str(use_real_filename).lower(),
        })
        return f"{os.getenv('BASE_URL', 'http://localhost:9000')}/v1/files/download?{params}"

    def get_file_as_base64(self, file_id: str) -> str:
        storage = self.db.query(FileStorage).filter(FileStorage.file_id == file_id).first()
        if not storage:
            raise HTTPException(status_code=404, detail="File not found")
        data = self.samba_client.download_file_to_bytes(storage.storage_path)
        return base64.b64encode(data).decode('utf-8')
