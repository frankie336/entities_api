# entities_api/clients/client.py

import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from ollama import Client as OllamaAPIClient

from entities_api.clients.client_actions_client import ClientActionService
from entities_api.clients.client_assistant_client import ClientAssistantService
from entities_api.clients.client_code_executor import ClientCodeService
from entities_api.clients.client_message_client import ClientMessageService
from entities_api.clients.client_run_client import RunService
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

        # Initialize service clients with type annotations
        self.user_service: UserService = UserService(self.base_url, self.api_key)
        self.assistant_service: ClientAssistantService = ClientAssistantService(self.base_url, self.api_key)
        self.tool_service: ClientToolService = ClientToolService(self.base_url, self.api_key)
        self.thread_service: ThreadService = ThreadService(self.base_url, self.api_key)
        self.message_service: ClientMessageService = ClientMessageService(self.base_url, self.api_key)
        self.run_service: RunService = RunService(self.base_url, self.api_key)
        self.actions_service: ClientActionService = ClientActionService(self.base_url, self.api_key)
        self.sandbox_service: SandboxClientService = SandboxClientService(self.base_url, self.api_key)
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
    def get_user_service(self) -> UserService:
        return self.user_service

    @property
    def get_assistant_service(self) -> ClientAssistantService:
        return self.assistant_service

    @property
    def get_tool_service(self) -> ClientToolService:
        return self.tool_service

    @property
    def get_thread_service(self) -> ThreadService:
        return self.thread_service

    @property
    def get_message_service(self) -> ClientMessageService:
        return self.message_service

    @property
    def get_run_service(self) -> RunService:
        return self.run_service

    @property
    def get_action_service(self) -> ClientActionService:
        return self.actions_service

    @property
    def get_sandbox_service(self) -> SandboxClientService:
        return self.sandbox_service

    @property
    def get_code_executor_service(self) -> ClientCodeService:
        return self.code_executor_service




