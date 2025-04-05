from entities_api.utils.samba_client import SambaClient
from dotenv import load_dotenv
import os

load_dotenv()

server = os.getenv("SMBCLIENT_SERVER")
share = os.getenv("SMBCLIENT_SHARE")
password = os.getenv("SMBCLIENT_PASSWORD")
user_name = os.getenv("SMBCLIENT_USERNAME")

client = SambaClient(
    server=server,
    share=share,
    password=password,
    username=user_name,
    port=1445
)

# Specify a local directory to save the file.
save_directory = "./downloaded_files"

# Download and save the file to disk.
saved_file_path = client.save_file_to_disk(file_id='file_1eMrvX72rFcX0ExzGkDnIf', save_dir=save_directory)

print("File saved to:", saved_file_path)
