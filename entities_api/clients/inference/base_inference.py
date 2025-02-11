import os
import time
import threading
from abc import ABC, abstractmethod
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

        # Common services setup
        self.user_service = UserService(self.base_url, self.api_key)
        self.assistant_service = ClientAssistantService(self.base_url, self.api_key)
        self.thread_service = ThreadService(self.base_url, self.api_key)
        self.message_service = ClientMessageService(self.base_url, self.api_key)
        self.run_service = ClientRunService(self.base_url, self.api_key)
        self.tool_service = ClientToolService(self.base_url, self.api_key)
        self.action_service = ClientActionService(self.base_url, self.api_key)

        logging_utility.info("BaseInference services initialized.")

        # Cancellation flag to be updated asynchronously
        self._cancelled = False

        self.setup_services()

    @abstractmethod
    def setup_services(self):
        """Initialize any additional services required by child classes."""
        pass

    @abstractmethod
    def process_conversation(self, *args, **kwargs):
        """Process the conversation and yield response chunks."""
        pass

    def handle_error(self, assistant_reply, thread_id, assistant_id, run_id):
        """If an error occurs and partial text output has been streamed,
        save the truncated text to the message dialogue
        """
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
        This thread continuously polls for a cancellation event and, if detected,
        sets the internal cancellation flag.
        """
        from entities_api.services.run_event_handler import EntitiesEventHandler

        def handle_event(event_type: str, event_data: Any):

            #logging_utility.info(f"[Callback] Event: {event_type}, Data: {event_data}")
            if event_type == "cancelled":
                return "cancelled"

        def listen_for_cancellation():
            event_handler = EntitiesEventHandler(
                run_service=self.run_service,
                action_service=self.action_service,
                event_callback=handle_event
            )
            while not self._cancelled:
                # This call is blocking inside the thread, so it won't block your main loop.
                if event_handler._emit_event("cancelled", run_id) == "cancelled":
                    self._cancelled = True
                    logging_utility.info(f"Cancellation event detected for run {run_id}")
                    break
                time.sleep(poll_interval)

        cancellation_thread = threading.Thread(target=listen_for_cancellation, daemon=True)
        cancellation_thread.start()

    def check_cancellation_flag(self) -> bool:
        """Non-blocking check of the cancellation flag."""
        return self._cancelled
