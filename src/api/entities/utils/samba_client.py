import hashlib
import hmac
import os
import socket
import time
import io
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from urllib.parse import urlencode

from entities.models.models import File
from fastapi import HTTPException
from smb.SMBConnection import SMBConnection


class SambaClient:
    def __init__(self, server: str, share: str, username: str, password: str,
                 domain: Optional[str] = None, port: int = 445,
                 max_retries: int = 5, retry_delay: int = 2):
        self.server = server
        self.share = share
        self.username = username
        self.password = password
        self.domain = domain or "WORKGROUP"
        self.port = port
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        self.client_name = socket.gethostname()
        self.server_name = server
        self.conn = None

        for retry in range(self.max_retries):
            try:
                print(f"Attempting to connect to SMB server (attempt {retry + 1}/{self.max_retries})...")
                self._connect()
                print(f"Successfully connected to SMB server on attempt {retry + 1}")
                break
            except Exception as e:
                print(f"Connection attempt {retry + 1} failed: {str(e)}")
                if retry < self.max_retries - 1:
                    print(f"Retrying in {self.retry_delay} seconds...")
                    time.sleep(self.retry_delay)
                else:
                    raise Exception(
                        f"Failed to connect to SMB server after {self.max_retries} attempts. Last error: {str(e)}")

    def _connect(self):
        connection_params: List[Dict[str, Any]] = [
            {"use_ntlm_v2": True, "is_direct_tcp": True},
            {"use_ntlm_v2": True, "is_direct_tcp": False},
            {"use_ntlm_v2": False, "is_direct_tcp": True},
            {"use_ntlm_v2": False, "is_direct_tcp": False}
        ]

        errors = []
        for params in connection_params:
            try:
                print(f"Trying connection with parameters: {params}")
                self.conn = SMBConnection(
                    self.username,
                    self.password,
                    self.client_name,
                    self.server_name,
                    domain=self.domain,
                    **params
                )

                try:
                    ip_address = socket.gethostbyname(self.server)
                    print(f"Resolved {self.server} to IP: {ip_address}")
                except socket.gaierror:
                    print(f"Warning: Could not resolve hostname {self.server}")

                if self.conn.connect(self.server, self.port):
                    print(f"Connected successfully with params: {params}")
                    return
                else:
                    error_msg = "Connection returned false"
                    print(f"{error_msg} with params: {params}")
                    errors.append(error_msg)
            except Exception as e:
                error_msg = str(e)
                print(f"Connection attempt failed with params {params}: {error_msg}")
                errors.append(error_msg)

        raise Exception(f"Failed to connect to SMB server. Errors: {', '.join(errors)}")

    def list_files(self, remote_dir: str = ""):
        try:
            files = self.conn.listPath(self.share, remote_dir)
            return [f.filename for f in files if f.filename not in [".", ".."]]
        except Exception as e:
            raise Exception(f"Failed to list files: {str(e)}")

    listdir = list_files

    def upload_file(self, local_path: str, remote_path: Optional[str] = None):
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"Local file not found: {local_path}")
        remote_path = remote_path or os.path.basename(local_path)
        try:
            with open(local_path, "rb") as file_obj:
                self.conn.storeFile(self.share, remote_path, file_obj)
        except Exception as e:
            raise Exception(f"Failed to upload file: {str(e)}")

    def download_file(self, remote_path: str, local_path: Optional[str] = None):
        local_path = local_path or os.path.basename(remote_path)
        try:
            with open(local_path, "wb") as file_obj:
                self.conn.retrieveFile(self.share, remote_path, file_obj)
        except Exception as e:
            raise Exception(f"Failed to download file: {str(e)}")

    def download_file_to_bytes(self, remote_path: str) -> bytes:
        file_obj = io.BytesIO()
        try:
            self.conn.retrieveFile(self.share, remote_path, file_obj)
            file_obj.seek(0)
            return file_obj.read()
        except Exception as e:
            raise Exception(f"Failed to download file to bytes: {str(e)}")

    def delete_file(self, remote_path: str):
        try:
            self.conn.deleteFiles(self.share, remote_path)
        except Exception as e:
            raise Exception(f"Failed to delete file: {str(e)}")

    def create_directory(self, remote_dir: str):
        try:
            self.conn.createDirectory(self.share, remote_dir)
        except Exception as e:
            raise Exception(f"Failed to create directory: {str(e)}")

    def delete_directory(self, remote_dir: str):
        try:
            self.conn.deleteDirectory(self.share, remote_dir)
        except Exception as e:
            raise Exception(f"Failed to delete directory: {str(e)}")

    def rename(self, old_remote_path: str, new_remote_path: str):
        try:
            self.conn.rename(self.share, old_remote_path, new_remote_path)
        except Exception as e:
            raise Exception(f"Failed to rename file/directory: {str(e)}")

    def get_file_as_signed_url(self, file_id: str, expires_in: int = 3600) -> str:
        file_record = self.db.query(File).filter(File.id == file_id).first()
        if not file_record:
            raise HTTPException(status_code=404, detail=f"File with ID {file_id} not found")

        secret_key = os.getenv("SIGNED_URL_SECRET", "default_secret_key")
        expiration_time = datetime.utcnow() + timedelta(seconds=expires_in)
        expiration_timestamp = int(expiration_time.timestamp())
        data = f"{file_id}:{expiration_timestamp}"
        signature = hmac.new(
            key=secret_key.encode(),
            msg=data.encode(),
            digestmod=hashlib.sha256
        ).hexdigest()

        query_params = {
            "file_id": file_id,
            "expires": expiration_timestamp,
            "signature": signature,
        }
        base_url = os.getenv("BASE_URL", "http://localhost:9000")
        signed_url = f"{base_url}/v1/files/download?{urlencode(query_params)}"
        return signed_url

