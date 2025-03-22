import os
import socket
import time
from typing import Optional, List, Dict, Any
from smb.SMBConnection import SMBConnection


class SambaClient:
    def __init__(self, server: str, share: str, username: str, password: str,
                 domain: Optional[str] = None, port: int = 445,
                 max_retries: int = 5, retry_delay: int = 2):
        """
        Initialize the Samba client using pysmb's SMBConnection.

        :param server: Samba server hostname or IP address.
        :param share: Samba share name.
        :param username: Samba username.
        :param password: Samba password.
        :param domain: Optional domain name (default is "WORKGROUP").
        :param port: Port to connect to (default is 445).
        :param max_retries: Maximum number of connection attempts (default is 5).
        :param retry_delay: Delay between retries in seconds (default is 2).
        """
        self.server = server
        self.share = share
        self.username = username
        self.password = password
        self.domain = domain or "WORKGROUP"
        self.port = port
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Set the client name to the local hostname.
        self.client_name = socket.gethostname()
        # The server name can be set to the same as the server parameter.
        self.server_name = server

        # Create an SMB connection
        self.conn = None

        # Try to establish connection with retries
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
        """Establish connection to the SMB server with fallback options"""
        # Try connecting with different parameter combinations
        connection_params: List[Dict[str, Any]] = [
            # Try direct TCP with NTLMv2
            {"use_ntlm_v2": True, "is_direct_tcp": True},
            # Try without direct TCP
            {"use_ntlm_v2": True, "is_direct_tcp": False},
            # Try with NTLM v1
            {"use_ntlm_v2": False, "is_direct_tcp": True},
            # Try with NTLM v1 without direct TCP
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

                # Add additional debug info
                print(f"Attempting to connect to {self.server}:{self.port}")

                # Try name resolution before connection
                try:
                    ip_address = socket.gethostbyname(self.server)
                    print(f"Resolved {self.server} to IP: {ip_address}")
                except socket.gaierror:
                    print(f"Warning: Could not resolve hostname {self.server}")
                    # If we're in Docker, this might be a container name
                    # We'll try to connect anyway

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

        # If we get here, all connection attempts failed
        raise Exception(f"Failed to connect to SMB server. Errors: {', '.join(errors)}")

    def list_files(self, remote_dir: str = ""):
        """
        List files in a directory on the Samba share.
        :param remote_dir: Directory on the Samba share (use forward slashes, default is root).
        :return: List of file names.
        """
        try:
            files = self.conn.listPath(self.share, remote_dir)
            # Skip the '.' and '..' entries.
            return [f.filename for f in files if f.filename not in [".", ".."]]
        except Exception as e:
            raise Exception(f"Failed to list files: {str(e)}")

    # Alias to match sample usage.
    listdir = list_files

    def upload_file(self, local_path: str, remote_path: Optional[str] = None):
        """
        Upload a file to the Samba share.
        :param local_path: Path to the local file.
        :param remote_path: Destination path on the Samba share (defaults to the file's name).
        """
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"Local file not found: {local_path}")
        remote_path = remote_path or os.path.basename(local_path)
        try:
            with open(local_path, "rb") as file_obj:
                self.conn.storeFile(self.share, remote_path, file_obj)
        except Exception as e:
            raise Exception(f"Failed to upload file: {str(e)}")

    def download_file(self, remote_path: str, local_path: Optional[str] = None):
        """
        Download a file from the Samba share.
        :param remote_path: Path to the file on the Samba share.
        :param local_path: Destination path on the local system (defaults to the file's name).
        """
        local_path = local_path or os.path.basename(remote_path)
        try:
            with open(local_path, "wb") as file_obj:
                self.conn.retrieveFile(self.share, remote_path, file_obj)
        except Exception as e:
            raise Exception(f"Failed to download file: {str(e)}")

    def delete_file(self, remote_path: str):
        """
        Delete a file from the Samba share.
        :param remote_path: Path to the file on the Samba share.
        """
        try:
            self.conn.deleteFiles(self.share, remote_path)
        except Exception as e:
            raise Exception(f"Failed to delete file: {str(e)}")

    def create_directory(self, remote_dir: str):
        """
        Create a directory on the Samba share.
        :param remote_dir: Path to the directory on the Samba share.
        """
        try:
            self.conn.createDirectory(self.share, remote_dir)
        except Exception as e:
            raise Exception(f"Failed to create directory: {str(e)}")

    def delete_directory(self, remote_dir: str):
        """
        Delete a directory from the Samba share.
        :param remote_dir: Path to the directory on the Samba share.
        """
        try:
            self.conn.deleteDirectory(self.share, remote_dir)
        except Exception as e:
            raise Exception(f"Failed to delete directory: {str(e)}")

    def rename(self, old_remote_path: str, new_remote_path: str):
        """
        Rename a file or directory on the Samba share.
        :param old_remote_path: Existing file/directory path on the Samba share.
        :param new_remote_path: New file/directory path on the Samba share.
        """
        try:
            self.conn.rename(self.share, old_remote_path, new_remote_path)
        except Exception as e:
            raise Exception(f"Failed to rename file/directory: {str(e)}")


