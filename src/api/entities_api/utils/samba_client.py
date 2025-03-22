import os
import socket
from typing import Optional
from smb.SMBConnection import SMBConnection

class SambaClient:
    def __init__(self, server: str, share: str, username: str, password: str,
                 domain: Optional[str] = None, port: int = 445):
        """
        Initialize the Samba client using pysmb's SMBConnection.

        Note: To align with your container configuration, ensure that:
          - share is set to "cosmic_share"
          - username is set to "samba_user"
          - password matches the Samba user's password

        :param server: Samba server hostname or IP address.
                       (Within your Docker network, use the service name, e.g., "samba_server".)
                       If connecting externally via port mapping, use the host IP.
        :param share: Samba share name (should be "cosmic_share" per container configuration).
        :param username: Samba username (typically "samba_user").
        :param password: Samba password.
        :param domain: Optional domain name (use "WORKGROUP" or leave as None if not in an AD environment).
        :param port: Port to connect to (default is 445; if using custom host port mapping, adjust accordingly).
        """
        self.server = server
        self.share = share
        self.username = username
        self.password = password
        self.domain = domain
        self.port = port

        # Set the client name to the local hostname.
        self.client_name = socket.gethostname()
        # The server name can be set to the same as the server parameter.
        self.server_name = server

        # Create an SMB connection
        self.conn = SMBConnection(username, password, self.client_name,
                                  self.server_name, domain=domain, use_ntlm_v2=True)
        if not self.conn.connect(server, port):
            raise Exception("Failed to connect to SMB server")

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


if __name__ == "__main__":
    # Example test usage:
    # Update these parameters to match your local testing environment.
    # Within Docker, you might use server="samba_server" and share="cosmic_share".
    # For external testing using host port mapping, use server="localhost" and adjust port accordingly.

    server = "localhost"  # or "localhost" if testing externally
    share = "cosmic_share"
    username = "samba_user"
    password = "default"

    port = 1445  # Change this to 1445 if you're using the custom host port mapping externally

    try:
        smb = SambaClient(server, share, username, password, port=port)
        files = smb.listdir("")
        print("Files in share:", files)
    except Exception as e:
        print("Error:", e)
