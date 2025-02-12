import json
import re
import time
import requests
from dotenv import load_dotenv
from entities_api.clients.client_run_client import ClientRunService
from entities_api.clients.inference.base_inference import BaseInference
from entities_api.clients.client_message_client import ClientMessageService
from entities_api.clients.client_actions_client import ClientActionService
from entities_api.services.logging_service import LoggingUtility

# Load environment variables from .env file
load_dotenv()

# Initialize logging utility
logging_utility = LoggingUtility()


class HyperbolicV3Inference(BaseInference):
    def setup_services(self):
        """Initialize the Hyperbolic API service."""
        self.api_url = "https://api.hyperbolic.xyz/v1/chat/completions"
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJwcmltZS50aGFub3MzMzZAZ21haWwuY29tIiwiaWF0IjoxNzM4NDc2MzgyfQ.4V27eTb-TRwPKcA5zit4pJckoEUEa7kxmHwFEn9kwTQ"
        }
        logging_utility.info("HyperbolicInference specific setup completed.")

    def normalize_roles(self, conversation_history):
        """Normalize roles to ensure consistency with the Hyperbolic API."""
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

    def detect_tool_call(self, chunks):
        """
        Accumulates chunks and returns the complete tool call JSON string if it matches the expected pattern.

        Expected pattern example:
        {"name": "fetch_flight_times", "arguments": {"origin": "LAX", "destination": "JFK"}}

        Args:
            chunks (list of str): The accumulated text chunks.

        Returns:
            str or None: The complete tool call JSON string if detected; otherwise, None.
        """
        # Regex to match a JSON object with "name" and "arguments" keys.
        pattern = re.compile(
            r'^\s*\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:\s*\{[^}]*\}\s*\}\s*$'
        )
        accumulated = "".join(chunks)
        if pattern.match(accumulated):
            return accumulated
        return None

    def process_conversation(self, thread_id, message_id, run_id, assistant_id,
                             model='deepseek-ai/DeepSeek-R1', stream_reasoning=True):
        """
        Process conversation using the Hyperbolic API via raw HTTP requests.

        This method accumulates chunks from the stream and uses regex to detect the tool call pattern.
        Once detected, it logs and processes the tool call, then returns the complete tool call string.
        """
        logging_utility.info(
            "Processing conversation for thread_id: %s, run_id: %s, assistant_id: %s",
            thread_id, run_id, assistant_id
        )

        self.start_cancellation_listener(run_id)
        assistant = self.assistant_service.retrieve_assistant(assistant_id=assistant_id)
        logging_utility.info(
            "Retrieved assistant: id=%s, name=%s, model=%s",
            assistant.id, assistant.name, assistant.model
        )

        conversation_history = self.message_service.get_formatted_messages(
            thread_id, system_message=assistant.instructions
        )
        conversation_history = self.normalize_roles(conversation_history)
        messages = [{"role": msg['role'], "content": msg['content']} for msg in conversation_history]

        payload = {
            "messages": messages,
            "model": model,
            "stream": True,
            "max_tokens": 100000,
            "temperature": 0.6,
            "top_p": 0.9
        }

        assistant_reply = ""
        accumulated_tool_chunks = []
        complete_tool_call = None

        try:
            response = requests.post(
                self.api_url,
                headers=self.headers,
                json=payload,
                stream=True,
                timeout=60
            )
            response.raise_for_status()

            for line in response.iter_lines(decode_unicode=True):
                if self.check_cancellation_flag():
                    logging_utility.warning("Run %s cancelled mid-stream. Terminating stream.", run_id)
                    break

                if not line:
                    continue

                if line.startswith("data:"):
                    line = line[len("data:"):].strip()

                if line == "[DONE]":
                    break

                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    logging_utility.error("Failed to decode JSON from chunk: %s", line)
                    continue

                current_run = self.run_service.retrieve_run(run_id)
                if current_run.status in ["cancelling", "cancelled"]:
                    logging_utility.warning("Run %s cancelled during streaming", run_id)
                    break

                choices = chunk.get("choices", [])
                if not choices:
                    continue

                delta = choices[0].get("delta", {})
                content_chunk = delta.get("content", "")

                if content_chunk:
                    # Process the content chunk.
                    accumulated_tool_chunks.append(content_chunk)
                    complete_tool_call = self.detect_tool_call(accumulated_tool_chunks)
                    if complete_tool_call:
                        logging_utility.info("*** Complete Tool Structure Detected! ***")
                        logging_utility.info("Tool call content: %s", complete_tool_call)

                        # Save the assistant's tool call to dialogue.
                        message_service = ClientMessageService()
                        message_service.save_assistant_message_chunk(
                            thread_id=thread_id,
                            role='assistant',
                            content=complete_tool_call,
                            assistant_id=assistant_id,
                            sender_id=assistant_id,
                            is_last_chunk=True
                        )

                        # Process the tool invocation.
                        tool_data = json.loads(complete_tool_call)
                        action_service = ClientActionService()
                        action_service.create_action(
                            tool_name=tool_data['name'],
                            run_id=run_id,
                            function_args=tool_data['arguments']
                        )

                        # Update run status to 'action_required'.
                        run_service = ClientRunService()
                        run_service.update_run_status(run_id=run_id, new_status='action_required')
                        logging_utility.info("Run %s status updated to action_required", run_id)

                        # Wait for the run's status to change from 'action_required'.
                        while True:
                            run = self.run_service.retrieve_run(run_id)
                            if run.status != "action_required":
                                break
                            time.sleep(1)
                        logging_utility.info("Action status transition complete. Reprocessing conversation.")
                        break
                    else:
                        assistant_reply += content_chunk
                        logging_utility.info("Processing content chunk: %s", content_chunk)

        except Exception as e:
            error_msg = "[ERROR] Hyperbolic API streaming error"
            logging_utility.error("%s: %s", error_msg, str(e), exc_info=True)
            self.handle_error(assistant_reply, thread_id, assistant_id, run_id)

        if assistant_reply:
            self.finalize_conversation(assistant_reply, thread_id, assistant_id, run_id)

        return complete_tool_call
