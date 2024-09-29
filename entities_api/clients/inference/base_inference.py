from abc import ABC, abstractmethod
from entities_api.clients.client_actions_client import ClientActionService
from entities_api.clients.client_assistant_client import ClientAssistantService
from entities_api.clients.client_message_client import ClientMessageService
from entities_api.clients.client_run_client import RunService
from entities_api.clients.client_thread_client import ThreadService
from entities_api.clients.client_tool_client import ClientToolService
from entities_api.clients.client_user_client import UserService
from entities_api.services.logging_service import LoggingUtility


class BaseInference(ABC):
    def __init__(self, base_url, api_key, available_functions):
        self.base_url = base_url
        self.api_key = api_key
        self.available_functions = available_functions

        # Common services setup
        self.user_service = UserService(self.base_url, self.api_key)
        self.assistant_service = ClientAssistantService(self.base_url, self.api_key)
        self.thread_service = ThreadService(self.base_url, self.api_key)
        self.message_service = ClientMessageService(self.base_url, self.api_key)
        self.run_service = RunService(self.base_url, self.api_key)
        self.tool_service = ClientToolService(self.base_url, self.api_key)
        self.action_service = ClientActionService(self.base_url, self.api_key)

        logging_utility = LoggingUtility()
        logging_utility.info("BaseInference services initialized.")

        self.setup_services()

    @abstractmethod
    def setup_services(self):
        """Initialize any additional services required by child classes."""
        pass

    @abstractmethod
    def process_conversation(self, *args, **kwargs):
        """Process the conversation and yield response chunks."""
        pass
