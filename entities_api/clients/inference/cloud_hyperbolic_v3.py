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
        """ Initialize the Hyperbolic API service. """
        self.api_url = "https://api.hyperbolic.xyz/v1/chat/completions"
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJwcmltZS50aGFub3MzMzZAZ21haWwuY29tIiwiaWF0IjoxNzM4NDc2MzgyfQ.4V27eTb-TRwPKcA5zit4pJckoEUEa7kxmHwFEn9kwTQ"
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

    def strict_detect_tool_call_minimal(self, buffer):
        """
        Returns True if the buffer strictly follows the expected order:
        {"name": "<function_name>", "arguments": {
        Otherwise, returns False.
        """
        cleaned = buffer.strip()
        regex = r'^\s*{\s*"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:\s*{'
        return bool(re.match(regex, cleaned))

    def process_conversation(self, thread_id, message_id, run_id, assistant_id,
                             model='deepseek-ai/DeepSeek-R1', stream_reasoning=True):
        """
        Process conversation using the Hyperbolic API via raw HTTP requests.
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
        function_buffer = ""
        MIN_TRIGGER_CHARS = 15
        MAX_NORMAL_CHARS = 40

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
                    logging_utility.warning(f"Run {run_id} cancelled mid-stream. Terminating stream.")
                    yield json.dumps({'type': 'error', 'content': 'Run was cancelled.'})
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
                    function_buffer += content_chunk
                    if len(function_buffer) >= MIN_TRIGGER_CHARS:
                        if self.strict_detect_tool_call_minimal(function_buffer):
                            logging_utility.info("*** Tool Trigger Detected! ***")
                            yield json.dumps({'type': 'tool_call', 'content': function_buffer})
                            break
                        elif len(function_buffer) > MAX_NORMAL_CHARS:
                            logging_utility.info("Buffer exceeds normal threshold; flushing.")
                            function_buffer = ""

                    assistant_reply += content_chunk
                    logging_utility.info("Yielding content chunk: %s", content_chunk)
                    yield json.dumps({'type': 'content', 'content': content_chunk})

        except Exception as e:
            error_msg = "[ERROR] Hyperbolic API streaming error"
            logging_utility.error(f"{error_msg}: {str(e)}", exc_info=True)
            self.handle_error(assistant_reply, thread_id, assistant_id, run_id)
            yield json.dumps({'type': 'error', 'content': error_msg})
            return

        if assistant_reply:
            self.finalize_conversation(assistant_reply, thread_id, assistant_id, run_id)
