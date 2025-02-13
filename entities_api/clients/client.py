# entities_api/clients/client.py
import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from ollama import Client as OllamaAPIClient

from entities_api.clients.client_actions_client import ClientActionService
from entities_api.clients.client_assistant_client import ClientAssistantService
from entities_api.clients.client_message_client import ClientMessageService
from entities_api.clients.client_run_client import ClientRunService
from entities_api.clients.client_sandbox_client import SandboxClientService
from entities_api.clients.client_thread_client import ThreadService
from entities_api.clients.client_tool_client import ClientToolService
from entities_api.clients.client_user_client import UserService
from entities_api.services.logging_service import LoggingUtility

# Load environment variables from .env file
load_dotenv()

# Initialize logging utility
logging_utility = LoggingUtility()


class OllamaClient:
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

        # Initialize the Ollama API client
        self.ollama_client: OllamaAPIClient = OllamaAPIClient()

        logging_utility.info("OllamaClient initialized with base_url: %s", self.base_url)

        # Lazy initialization caches for service instances
        self._user_service: Optional[UserService] = None
        self._assistant_service: Optional[ClientAssistantService] = None
        self._tool_service: Optional[ClientToolService] = None
        self._thread_service: Optional[ThreadService] = None
        self._message_service: Optional[ClientMessageService] = None
        self._run_service: Optional[ClientRunService] = None
        self._action_service: Optional[ClientActionService] = None
        self._sandbox_service: Optional[SandboxClientService] = None

    @property
    def user_service(self) -> UserService:
        if self._user_service is None:
            self._user_service = UserService(base_url=self.base_url, api_key=self.api_key)
        return self._user_service

    @property
    def assistant_service(self) -> ClientAssistantService:
        if self._assistant_service is None:
            self._assistant_service = ClientAssistantService(base_url=self.base_url, api_key=self.api_key)
        return self._assistant_service

    @property
    def tool_service(self) -> ClientToolService:
        if self._tool_service is None:
            # Consider adding dependency injection here if ClientToolService grows more complex.
            self._tool_service = ClientToolService()
        return self._tool_service

    @property
    def thread_service(self) -> ThreadService:
        if self._thread_service is None:
            self._thread_service = ThreadService(base_url=self.base_url, api_key=self.api_key)
        return self._thread_service

    @property
    def message_service(self) -> ClientMessageService:
        if self._message_service is None:
            self._message_service = ClientMessageService(base_url=self.base_url, api_key=self.api_key)
        return self._message_service

    @property
    def run_service(self) -> ClientRunService:
        if self._run_service is None:
            self._run_service = ClientRunService()
        return self._run_service

    @property
    def action_service(self) -> ClientActionService:
        if self._action_service is None:
            self._action_service = ClientActionService()
        return self._action_service

    @property
    def sandbox_service(self) -> SandboxClientService:
        if self._sandbox_service is None:
            self._sandbox_service = SandboxClientService(base_url=self.base_url, api_key=self.api_key)
        return self._sandbox_service
