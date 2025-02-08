# entities_api/clients/inference/hyperbolic_base.py
import json

import requests
from dotenv import load_dotenv

from entities_api.clients.client import ClientRunService
from entities_api.clients.client_assistant_client import ClientAssistantService
from entities_api.clients.client_message_client import ClientMessageService
from entities_api.clients.inference.base_inference import BaseInference
from entities_api.services.logging_service import LoggingUtility

load_dotenv()
logging_utility = LoggingUtility()

class HyperbolicBaseInference(BaseInference):
    """
    Base class for Hyperbolic API implementations with common functionality
    """
    DEFAULT_MODEL = None  # Must be set in subclasses
    DEFAULT_TEMPERATURE = 0.5
    DEFAULT_TOP_P = 0.9

    def __init__(self):
        self.api_url = "https://api.hyperbolic.xyz/v1/chat/completions"
        self.headers = self._get_auth_headers()
        self._setup_complete = False

    def _get_auth_headers(self):
        """Centralized auth header configuration"""
        return {
            "Content-Type": "application/json",
            "Authorization": (
                "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
                "eyJzdWIiOiJwcmltZS50aGFub3MzMzZAZ21haWwuY29tIiwiaWF0IjoxNzM4NDc2MzgyfQ."
                "4V27eTb-TRwPKcA5zit4pJckoEUEa7kxmHwFEn9kwTQ"
            )
        }

    def setup_services(self):
        """Common service setup for all Hyperbolic implementations"""
        if not self._setup_complete:
            logging_utility.info("Initializing Hyperbolic API services")
            self._setup_complete = True

    def normalize_roles(self, conversation_history):
        """Shared role normalization logic"""
        normalized_history = []
        for message in conversation_history:
            role = message.get('role', '').strip().lower()
            if role not in ['user', 'assistant', 'system']:
                role = 'user'
            normalized_history.append({
                "role": role,
                "content": message.get('content', '').strip()
            })
        return normalized_history

    def create_payload(self, messages, model=None, **kwargs):
        """Construct base payload with model-specific defaults"""
        return {
            "messages": messages,
            "model": model or self.DEFAULT_MODEL,
            "stream": True,
            "max_tokens": 100000,
            "temperature": kwargs.get('temperature', self.DEFAULT_TEMPERATURE),
            "top_p": kwargs.get('top_p', self.DEFAULT_TOP_P)
        }

    def process_conversation(self, thread_id, message_id, run_id, assistant_id,
                            model=None, **kwargs):
        """
        Core conversation processing flow with hook for model-specific handling
        """
        self.setup_services()
        logging_utility.info(
            f"Processing conversation for thread: {thread_id}, "
            f"run: {run_id}, assistant: {assistant_id}"
        )

        assistant_service = ClientAssistantService()
        assistant = assistant_service.retrieve_assistant(assistant_id)

        message_service = ClientMessageService()
        conversation_history = message_service.get_formatted_messages(
            thread_id, system_message=assistant.instructions
        )
        messages = self.normalize_roles(conversation_history)

        payload = self.create_payload(
            messages=messages,
            model=model,
            **kwargs
        )

        try:
            response = requests.post(
                self.api_url,
                headers=self.headers,
                json=payload,
                stream=True,
                timeout=60
            )
            response.raise_for_status()

            assistants_response = ""

            for line in self._process_stream(response, run_id):
                assistants_response += line
                yield line

            self._finalize_run(run_id=run_id, assistant_id=assistant_id,
                               thread_id=thread_id, role='assistant',
                               content=assistants_response, sender_id=assistant_id)

        except Exception as e:
            yield from self._handle_error(e, run_id=run_id, thread_id=thread_id,
                                          role='assistant', content=assistants_response,
                                          assistant_id=assistant_id, sender_id=assistant_id )

    def _process_stream(self, response, run_id):
        """Stream processing pipeline with cancellation checks"""
        for line in response.iter_lines(decode_unicode=True):
            if self._check_cancellation(run_id):
                break

            processed = self.process_line(line)
            if processed:
                yield processed
               #time.sleep(0.001)

    def process_line(self, line):
        """Model-specific line processing (to be overridden)"""
        raise NotImplementedError("Subclasses must implement process_line")

    def _check_cancellation(self, run_id):
        """Shared cancellation check logic"""

        run_service = ClientRunService()
        current_run = run_service.retrieve_run(run_id)

        if current_run.status in ["cancelling", "cancelled"]:
            logging_utility.warning(f"Run {run_id} cancelled during streaming")
            return True
        return False

    def _finalize_run(self, run_id, assistant_id, thread_id, role, content, sender_id):
        """Common finalization tasks"""

        run_service = ClientRunService()
        message_service = ClientMessageService()
        message_service.save_assistant_message_chunk(thread_id, role, content, assistant_id, sender_id,
                                                     is_last_chunk=True)

        run_service.update_run_status(run_id, "completed")
        logging_utility.info(
            f"Completed processing for run {run_id} "
            f"(assistant: {assistant_id}, thread: {thread_id})"
        )

    def _handle_error(self, error, run_id, thread_id, role, content, assistant_id, sender_id):
        """Centralized error handling"""
        error_msg = f"API streaming error: {str(error)}"
        logging_utility.error(error_msg, exc_info=True)
        run_service = ClientRunService()

        message_service = ClientMessageService()
        message_service.save_assistant_message_chunk(thread_id, role, content, assistant_id, sender_id, is_last_chunk=True)

        run_service.update_run_status(run_id, "failed")
        yield json.dumps({'type': 'error', 'content': error_msg})