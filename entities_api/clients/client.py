# entities_api/clients/client.py

import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from ollama import Client as OllamaAPIClient

from entities_api.clients.client_actions_client import ClientActionService
from entities_api.clients.client_assistant_client import ClientAssistantService
from entities_api.clients.client_code_executor import ClientCodeService
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
        self.base_url = base_url or os.getenv('ASSISTANTS_BASE_URL', 'http://localhost:9000/')
        self.api_key = api_key or os.getenv('API_KEY', 'your_api_key')

        self.code_executor_service: ClientCodeService = ClientCodeService(
            sandbox_server_url=os.getenv('CODE_SERVER_URL', 'http://localhost:9000/v1/execute_code')
        )

        # Append code code_interpreter handler to available tools

        self.available_functions = available_functions or {}

        # Initialize the Ollama API client
        self.ollama_client: OllamaAPIClient = OllamaAPIClient()

        logging_utility.info("OllamaClient initialized with base_url: %s", self.base_url)

    # Service Accessors with Type Annotations
    @property
    def user_service(self) -> UserService:

        user_service = UserService(base_url=self.base_url, api_key=self.api_key)

        return user_service

    @property
    def assistant_service(self) -> ClientAssistantService:
        assistant_service = ClientAssistantService(base_url=self.base_url, api_key=self.api_key)
        return assistant_service

    @property
    def tool_service(self) -> ClientToolService:

        tool_service =  ClientToolService()

        return tool_service

    @property
    def thread_service(self) -> ThreadService:
        return ThreadService(base_url=self.base_url, api_key=self.api_key)


    @property
    def message_service(self) -> ClientMessageService:
        return ClientMessageService(base_url=self.base_url, api_key=self.api_key)

    @property
    def run_service(self) -> ClientRunService:
        return ClientRunService()

    @property
    def action_service(self) -> ClientActionService:
        return ClientActionService()

    @property
    def sandbox_service(self) -> SandboxClientService:
        return SandboxClientService(base_url=self.base_url, api_key=self.api_key)

    @property
    def code_executor_service(self) -> ClientCodeService:
        return self.code_executor_service

    @code_executor_service.setter
    def code_executor_service(self, value):
        self._code_executor_service = value




