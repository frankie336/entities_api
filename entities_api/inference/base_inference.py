import json
import os
import re
import threading
import time
from abc import ABC, abstractmethod
from functools import lru_cache
from typing import Any

from entities_api.clients.client_actions_client import ClientActionService
from entities_api.clients.client_assistant_client import ClientAssistantService
from entities_api.clients.client_message_client import ClientMessageService
from entities_api.clients.client_run_client import ClientRunService
from entities_api.clients.client_thread_client import ThreadService
from entities_api.clients.client_tool_client import ClientToolService
from entities_api.clients.client_user_client import UserService
from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()

class BaseInference(ABC):
    def __init__(self, base_url=os.getenv('ASSISTANTS_BASE_URL'), api_key=None, available_functions=None):
        self.base_url = base_url
        self.api_key = api_key
        self.available_functions = available_functions
        self._cancelled = False  # Cancellation flag
        self._services = {}  # Lazy-loaded services cache
        self.code_interpreter_response = False

        logging_utility.info("BaseInference initialized with lazy service loading.")

        self.setup_services()

    def _get_service(self, service_class):
        """Lazy-load and cache service instances."""
        if service_class not in self._services:
            self._services[service_class] = service_class(self.base_url, self.api_key)
            logging_utility.info(f"Lazy-loaded {service_class.__name__}")
        return self._services[service_class]

    @property
    def user_service(self):
        return self._get_service(UserService)

    @property
    def assistant_service(self):
        return self._get_service(ClientAssistantService)

    @property
    def thread_service(self):
        return self._get_service(ThreadService)

    @property
    def message_service(self):
        return self._get_service(ClientMessageService)

    @property
    def run_service(self):
        return self._get_service(ClientRunService)

    @property
    def tool_service(self):
        return self._get_service(ClientToolService)

    @property
    def action_service(self):
        return self._get_service(ClientActionService)

    @abstractmethod
    def setup_services(self):
        """Initialize any additional services required by child classes."""
        pass

    @abstractmethod
    def process_conversation(self, *args, **kwargs):
        """Process the conversation and yield response chunks."""
        pass

    @staticmethod
    def is_valid_function_call_response(json_data: json) -> bool:
        """
        Validates whether the input string is a correctly formed function call response.

        Expected structure:
        {
            "name": "function_name",
            "arguments": { "key1": "value1", "key2": "value2", ... }
        }

        - Ensures valid JSON.
        - Checks that "name" is a string.
        - Checks that "arguments" is a non-empty dictionary.

        :param json_data: JSON string representing a function call response.
        :return: True if valid, False otherwise.
        """
        try:

            # Ensure required keys exist
            if not isinstance(json_data, dict) or "name" not in json_data or "arguments" not in json_data:
                return False

            # Validate "name" is a non-empty string
            if not isinstance(json_data["name"], str) or not json_data["name"].strip():
                return False

            # Validate "arguments" is a dictionary with at least one key-value pair
            if not isinstance(json_data["arguments"], dict) or not json_data["arguments"]:
                return False

            return True  # Passed all checks

        except (json.JSONDecodeError, TypeError):
            return False  # Invalid JSON or unexpected structure

    def normalize_roles(self, conversation_history):
        """
        Normalize roles to ensure consistency with the Hyperbolic API.
        """
        normalized_history = []
        for message in conversation_history:
            role = message.get('role', '').strip().lower()
            if role not in ['user', 'assistant', 'system', 'tool']:
                role = 'user'
            normalized_history.append({
                "role": role,
                "content": message.get('content', '').strip()
            })
        return normalized_history

    def handle_error(self, assistant_reply, thread_id, assistant_id, run_id):
        """Handle errors and store partial assistant responses."""
        if assistant_reply:
            self.message_service.save_assistant_message_chunk(
                thread_id=thread_id,
                content=assistant_reply,
                role="assistant",
                assistant_id=assistant_id,
                sender_id=assistant_id,
                is_last_chunk=True
            )
            logging_utility.info("Partial assistant response stored successfully.")
            self.run_service.update_run_status(run_id, "failed")

    def finalize_conversation(self, assistant_reply, thread_id, assistant_id, run_id):
        """Finalize the conversation by storing the assistant's reply."""
        if assistant_reply:
            self.message_service.save_assistant_message_chunk(
                thread_id=thread_id,
                content=assistant_reply,
                role="assistant",
                assistant_id=assistant_id,
                sender_id=assistant_id,
                is_last_chunk=True
            )
            logging_utility.info("Assistant response stored successfully.")
            self.run_service.update_run_status(run_id, "completed")



    def start_cancellation_listener(self, run_id: str, poll_interval: float = 1.0) -> None:
        """
        Starts a background thread to listen for cancellation events.
        Only starts if it hasn't already been started.
        """
        from entities_api.services.event_handler import EntitiesEventHandler

        if hasattr(self, "_cancellation_thread") and self._cancellation_thread.is_alive():
            logging_utility.info("Cancellation listener already running.")
            return

        def handle_event(event_type: str, event_data: Any):
            if event_type == "cancelled":
                return "cancelled"

        def listen_for_cancellation():
            event_handler = EntitiesEventHandler(
                run_service=self.run_service,
                action_service=self.action_service,
                event_callback=handle_event
            )
            while not self._cancelled:
                if event_handler._emit_event("cancelled", run_id) == "cancelled":
                    self._cancelled = True
                    logging_utility.info(f"Cancellation event detected for run {run_id}")
                    break
                time.sleep(poll_interval)

        self._cancellation_thread = threading.Thread(target=listen_for_cancellation, daemon=True)
        self._cancellation_thread.start()

    def check_cancellation_flag(self) -> bool:
        """Non-blocking check of the cancellation flag."""
        return self._cancelled

    @lru_cache(maxsize=128)
    def cached_user_details(self, user_id):
        """Cache user details to avoid redundant API calls."""
        return self.user_service.get_user(user_id)

