import json
import re

import requests
from dotenv import load_dotenv

from entities_api.clients.inference.base_inference import BaseInference
from entities_api.services.logging_service import LoggingUtility

# Load environment variables from .env file
load_dotenv()

# Initialize logging utility
logging_utility = LoggingUtility()

class HyperbolicV3Inference(BaseInference):
    def setup_services(self):
        """
        Initialize the Hyperbolic API service.
        """
        self.api_url = "https://api.hyperbolic.xyz/v1/chat/completions"
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": (
                "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
                "eyJzdWIiOiJwcmltZS50aGFub3MzMzZAZ21haWwuY29tIiwiaWF0IjoxNzM4NDc2MzgyfQ."
                "4V27eTb-TRwPKcA5zit4pJckoEUEa7kxmHwFEn9kwTQ"
            )
        }
        logging_utility.info("HyperbolicInference specific setup completed.")

    def normalize_roles(self, conversation_history):
        """
        Normalize roles to ensure consistency with the Hyperbolic API.
        """
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

    def process_conversation(self, thread_id, message_id, run_id, assistant_id,
                             model='deepseek-ai/DeepSeek-R1', stream_reasoning=True):
        """
        Process conversation using the Hyperbolic API via raw HTTP requests.

        This version streams the API response as a normal stream without splitting
        out reasoning content.
        """
        logging_utility.info(
            "Processing conversation for thread_id: %s, run_id: %s, assistant_id: %s",
            thread_id, run_id, assistant_id
        )

        # Start the non-blocking cancellation listener
        self.start_cancellation_listener(run_id)

        # Retrieve assistant details
        assistant = self.assistant_service.retrieve_assistant(assistant_id=assistant_id)
        logging_utility.info(
            "Retrieved assistant: id=%s, name=%s, model=%s",
            assistant.id, assistant.name, assistant.model
        )

        # Retrieve and normalize conversation history
        conversation_history = self.message_service.get_formatted_messages(
            thread_id, system_message=assistant.instructions
        )
        conversation_history = self.normalize_roles(conversation_history)
        # Create messages in the expected format for the API
        messages = [{"role": msg['role'], "content": msg['content']} for msg in conversation_history]

        # Construct the request payload
        payload = {
            "messages": messages,
            "model": model,
            "stream": True,
            "max_tokens": 100000,
            "temperature": 0.6,
            "top_p": 0.9
        }

        assistant_reply = ""

        try:
            response = requests.post(
                self.api_url,
                headers=self.headers,
                json=payload,
                stream=True,
                timeout=60  # Adjust the timeout as needed
            )
            response.raise_for_status()

            # Process streamed responses line by line
            for line in response.iter_lines(decode_unicode=True):
                # Non-blocking cancellation check by polling the flag
                if self.check_cancellation_flag():
                    logging_utility.warning(f"Run {run_id} cancelled mid-stream. Terminating stream.")
                    yield json.dumps({'type': 'error', 'content': 'Run was cancelled.'})
                    break

                if not line:
                    continue

                # Remove the "data:" prefix if it exists
                if line.startswith("data:"):
                    line = line[len("data:"):].strip()

                # Check if the line indicates stream completion
                if line == "[DONE]":
                    break

                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    logging_utility.error("Failed to decode JSON from chunk: %s", line)
                    continue

                # Additional cancellation check based on run status
                current_run = self.run_service.retrieve_run(run_id)
                if current_run.status in ["cancelling", "cancelled"]:
                    logging_utility.warning("Run %s cancelled during streaming", run_id)
                    break

                # Extract data from the chunk
                choices = chunk.get("choices", [])
                if not choices:
                    continue

                delta = choices[0].get("delta", {})
                content_chunk = delta.get("content", "")

                if content_chunk:
                    assistant_reply += content_chunk
                    logging_utility.info("Yielding content chunk: %s", content_chunk)
                    yield json.dumps({'type': 'content', 'content': content_chunk})

                # Optionally, you could include a slight delay here:
                # time.sleep(0.001)  # slight pause to allow incremental delivery

        except Exception as e:
            error_msg = "[ERROR] Hyperbolic API streaming error"
            logging_utility.error(f"{error_msg}: {str(e)}", exc_info=True)
            # Handle error (if applicable, this method should be defined in your BaseInference)
            self.handle_error(assistant_reply, thread_id, assistant_id, run_id)
            yield json.dumps({'type': 'error', 'content': error_msg})
            return

        # Final state handling for successful completion
        if assistant_reply:
            self.finalize_conversation(assistant_reply, thread_id, assistant_id, run_id)
