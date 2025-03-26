# entities/clients/code_execution_client.py
import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from common.clients.files import FileClient
from common.services.logging_service import LoggingUtility

load_dotenv()

# Initialize logging utility
logging_utility = LoggingUtility()


class CommonEntitiesInternalInterface:
    def __init__(
            self,
            base_url: Optional[str] = None,
            api_key: Optional[str] = None,
            available_functions: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize the main client with configuration.
        Optionally, a configuration object could be injected here
        to decouple from environment variables for better testability.
        """
        self.base_url = base_url or os.getenv('ASSISTANTS_BASE_URL', 'http://localhost:9000/')
        self.api_key = api_key or os.getenv('API_KEY', 'your_api_key')
        logging_utility.info("CommonEntitiesInternalInterface initialized with base_url: %s", self.base_url)

        self._file_client: Optional[FileClient] = None

    @property
    def files(self) -> FileClient:
        if self._file_client is None:
            # Pass base_url and api_key to the FileClient
            self._file_client = FileClient(base_url=self.base_url, api_key=self.api_key)
        return self._file_client
