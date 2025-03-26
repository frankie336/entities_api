# entities/clients/files.py
import io
import mimetypes
import os
from typing import Dict, Any, Optional, BinaryIO

import httpx
from dotenv import load_dotenv
from pydantic import ValidationError

from common.schemas.files import FileResponse
from common.services.logging_service import LoggingUtility

load_dotenv()
logging_utility = LoggingUtility()


class FileClient:
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        """
        Initialize the FileClient with base_url and api_key.
        These values can be passed in or will be loaded from the environment.
        """
        self.base_url = base_url or os.getenv("BASE_URL", "http://localhost:9000")
        self.api_key = api_key or os.getenv("API_KEY", "your_api_key")
        self.client = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        logging_utility.info("FileClient initialized with base_url: %s", self.base_url)

    def upload_file(self, file_path: str, user_id: str, purpose: str,
                    metadata: Optional[Dict[str, Any]] = None) -> FileResponse:
        """
        Upload a file to the server, following the OpenAI files endpoint style.
        """
        filename = os.path.basename(file_path)
        mime_type, _ = mimetypes.guess_type(file_path)
        mime_type = mime_type or 'application/octet-stream'

        logging_utility.info("Uploading file: %s with purpose: %s for user: %s", file_path, purpose, user_id)

        try:
            with open(file_path, 'rb') as file_object:
                form_data = {
                    "purpose": purpose,
                    "user_id": user_id
                }
                files = {'file': (filename, file_object, mime_type)}

                response = self.client.post("/v1/uploads", data=form_data, files=files)
                response.raise_for_status()

                file_data = response.json()
                validated_response = FileResponse.model_validate(file_data)
                logging_utility.info("File uploaded successfully with id: %s", validated_response.id)
                return validated_response

        except ValidationError as e:
            logging_utility.error("Validation error: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while uploading file: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while uploading file: %s", str(e))
            raise

    def upload_file_object(self, file_object: BinaryIO, file_name: str, user_id: str, purpose: str,
                           metadata: Optional[Dict[str, Any]] = None) -> FileResponse:
        """
        Upload a file-like object to the server.
        """
        mime_type, _ = mimetypes.guess_type(file_name)
        mime_type = mime_type or 'application/octet-stream'

        logging_utility.info("Uploading file object: %s with purpose: %s for user: %s", file_name, purpose, user_id)

        try:
            form_data = {
                "purpose": purpose,
                "user_id": user_id
            }
            files = {'file': (file_name, file_object, mime_type)}

            response = self.client.post("/v1/uploads", data=form_data, files=files)
            response.raise_for_status()

            file_data = response.json()
            validated_response = FileResponse.model_validate(file_data)
            logging_utility.info("File uploaded successfully with id: %s", validated_response.id)
            return validated_response

        except ValidationError as e:
            logging_utility.error("Validation error: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while uploading file: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while uploading file: %s", str(e))
            raise

    def retrieve_file(self, file_id: str) -> FileResponse:
        """
        Retrieve file metadata by ID.
        """
        logging_utility.info("Retrieving file with ID: %s", file_id)

        try:
            response = self.client.get(f"/v1/uploads/{file_id}")
            response.raise_for_status()

            file_data = response.json()
            validated_response = FileResponse.model_validate(file_data)
            logging_utility.info("File metadata retrieved successfully for ID: %s", file_id)
            return validated_response

        except ValidationError as e:
            logging_utility.error("Validation error: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while retrieving file: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while retrieving file: %s", str(e))
            raise

    def delete_file(self, file_id: str) -> bool:
        """
        Delete a file by its ID from the server.
        """
        logging_utility.info("Attempting to delete file with ID: %s", file_id)

        try:
            response = self.client.delete(f"/v1/uploads/{file_id}")
            response.raise_for_status()
            deletion_result = response.json()
            logging_utility.info("File deletion result for ID %s: %s", file_id, deletion_result)
            return deletion_result

        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while deleting the file: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while deleting the file: %s", str(e))
            raise

    def download_file_as_object(self, file_id: str) -> io.BytesIO:
        """
        Retrieve file content as a file-like object (BytesIO).
        """
        try:
            response = self.client.get(f"/v1/uploads/{file_id}/object")
            response.raise_for_status()
            return io.BytesIO(response.content)
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error in download_file_as_object: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("Unexpected error in download_file_as_object: %s", str(e))
            raise

    def get_signed_url(self, file_id: str) -> str:
        """
        Retrieve a signed URL for the file.
        """
        try:
            response = self.client.get(f"/v1/uploads/{file_id}/signed-url")
            response.raise_for_status()
            data = response.json()
            return data.get("signed_url")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error in get_signed_url: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("Unexpected error in get_signed_url: %s", str(e))
            raise

    def get_file_as_base64(self, file_id: str) -> str:
        """
        Retrieve the file content as a BASE64-encoded string.
        """
        try:
            response = self.client.get(f"/v1/uploads/{file_id}/base64")
            response.raise_for_status()
            data = response.json()
            return data.get("base64")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error in get_file_as_base64: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("Unexpected error in get_file_as_base64: %s", str(e))
            raise
