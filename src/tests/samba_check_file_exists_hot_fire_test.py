import os
from dotenv import load_dotenv

load_dotenv()

from entities_api.utils.samba_client import SambaClient


def check_file_exists(expected_filename: str) -> bool:
    # Retrieve connection details from environment variables
    server = os.getenv("SMBCLIENT_SERVER")
    share = os.getenv("SMBCLIENT_SHARE")
    username = os.getenv("SMBCLIENT_USERNAME")
    password = os.getenv("SMBCLIENT_PASSWORD")
    domain = os.getenv("SMBCLIENT_DOMAIN", "WORKGROUP")
    port = int(os.getenv("SMBCLIENT_PORT", "445"))

    # Debug prints to ensure values are loaded
    print("SMBCLIENT_SERVER:", server)
    print("SMBCLIENT_SHARE:", share)
    print("SMBCLIENT_USERNAME:", username)
    print("SMBCLIENT_PASSWORD:", password)
    print("SMBCLIENT_DOMAIN:", domain)
    print("SMBCLIENT_PORT:", port)

    # Ensure that none of these are None
    if not all([server, share, username, password]):
        print("One or more required SMB environment variables are not set.")
        return False

    try:
        # Instantiate SambaClient with the retrieved values
        samba_client = SambaClient(server, share, username, password, domain, port)
        # List files in the root directory of the share
        files = samba_client.listdir("")
        print("Files in share:", files)
        # Check if the expected filename exists
        return expected_filename in files
    except Exception as e:
        print(f"Error checking file existence: {e}")
        return False


if __name__ == "__main__":
    file_to_check = "test_file.txt"  # Adjust if needed (e.g., your generated file id)
    exists = check_file_exists(file_to_check)
    print(f"File '{file_to_check}' exists: {exists}")
