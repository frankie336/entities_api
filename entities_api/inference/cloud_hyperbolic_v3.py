import json
import re
import time
import requests
from dotenv import load_dotenv
from entities_api.inference.base_inference import BaseInference
from entities_api.clients.client_message_client import ClientMessageService
from entities_api.clients.client_actions_client import ClientActionService
from entities_api.clients.client_run_client import ClientRunService
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
            if role not in ['user', 'assistant', 'system', 'tool']:
                role = 'user'
            normalized_history.append({
                "role": role,
                "content": message.get('content', '').strip()
            })
        return normalized_history

    @staticmethod
    def check_tool_call_data(input_string: str) -> bool:
        """Regex to match the general structure of a tool call JSON string."""
        pattern = r'^\{"name":\s*"[^"]+",\s*"arguments":\s*\{(?:\s*"[^"]*":\s*"[^"]*",\s*)*(?:"[^"]*":\s*"[^"]*")\s*\}\}$'
        return bool(re.match(pattern, input_string))

    def parse_tools_calls(self, thread_id, message_id, run_id, assistant_id, model='deepseek-ai/DeepSeek-R1'):
        """
        Processes streamed tool call content as a single accumulating string.
        Accumulates all chunks and returns the complete content at the end.
        """
        logging_utility.info("Scanning for tool calls: thread_id=%s, run_id=%s, assistant_id=%s",
                             thread_id, run_id, assistant_id)

        self.start_cancellation_listener(run_id)

        assistant = self.assistant_service.retrieve_assistant(assistant_id=assistant_id)

        messages = self.normalize_roles(
            self.message_service.get_formatted_messages(thread_id, system_message=assistant.instructions)
        )

        payload = {
            "messages": [{"role": msg['role'], "content": msg['content']} for msg in messages],
            "model": model,
            "stream": True,
            "max_tokens": 100000,
            "temperature": 0.6,
            "top_p": 0.9
        }

        accumulated_content = ""

        try:
            response = requests.post(self.api_url, headers=self.headers, json=payload, stream=True, timeout=60)
            response.raise_for_status()

            for line in response.iter_lines(decode_unicode=True):
                if self.check_cancellation_flag():
                    logging_utility.warning("Run %s cancelled. Terminating stream.", run_id)
                    break

                if not line or not line.startswith("data:"):
                    continue

                line_content = line[5:].strip()  # Strip "data:" prefix

                if line_content == "[DONE]":
                    logging_utility.info("Stream finished.")
                    continue

                try:
                    chunk = json.loads(line_content)
                    delta_content = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")

                    if delta_content:
                        logging_utility.info("Extracted delta content: %s", delta_content)
                        accumulated_content += delta_content

                        # Immediate validation after EVERY accumulation
                        if len(accumulated_content) >= 2:


                            if not accumulated_content.startswith('{"'):

                                print(accumulated_content)
                                print("Early exit!")

                                #time.sleep(1000)

                                logging_utility.warning("Invalid JSON start: %s", accumulated_content)
                                return accumulated_content
                            elif len(accumulated_content) == 2:
                                # Early validation for minimum valid start
                                return accumulated_content

                except json.JSONDecodeError:
                    logging_utility.error("JSON decoding failed for chunk: %s", line_content)

        except Exception as e:
            logging_utility.error("[ERROR] API streaming failure: %s", str(e), exc_info=True)
            self.handle_error("", thread_id, assistant_id, run_id)

        # Final validation before returning
        #if not self.check_tool_call_data(accumulated_content):
            #logging_utility.warning("Final content failed validation: %s", accumulated_content)
            #return ""

        logging_utility.info("accumulated_content: %s", accumulated_content)
        return accumulated_content

    def process_tool_calls(self, message_id, thread_id, assistant_id, content, run_id):
        """Handles the execution and state transition of a tool call."""
        message_service = ClientMessageService()
        message_data = message_service.retrieve_message(message_id=message_id)
        message = message_data.content

        self.message_service.save_assistant_message_chunk(
            thread_id=thread_id,
            content=content,
            role="assistant",
            assistant_id=assistant_id,
            sender_id=assistant_id,
            is_last_chunk=True
        )
        logging_utility.info("Saved triggering message to thread: %s", thread_id)

        action_service = ClientActionService()

        try:
            content_dict = json.loads(content)
        except json.JSONDecodeError as e:
            logging_utility.error(f"Error decoding accumulated content: {e}")
            return

        action_service.create_action(
            tool_name=content_dict["name"],
            run_id=run_id,
            function_args=content_dict["arguments"]
        )

        run_service = ClientRunService()
        run_service.update_run_status(run_id=run_id, new_status='action_required')
        logging_utility.info(f"Run {run_id} status updated to action_required")

        while True:
            run = self.run_service.retrieve_run(run_id)
            if run.status != "action_required":
                break
            time.sleep(1)

        logging_utility.info("Action status transition complete. Reprocessing conversation.")

        return content

    def process_conversation(self, thread_id, message_id, run_id, assistant_id,
                             model='deepseek-ai/DeepSeek-R1', stream_reasoning=True):
        """
        Process conversation using the Hyperbolic API via raw HTTP requests.
        """

        # First, process and scan for tool calls.
        tool_candidate_data = self.parse_tools_calls(thread_id=thread_id, message_id=message_id,
                                                     assistant_id=assistant_id, run_id=run_id, model=model)

        # Validate the tool_call_data_structure
        is_this_a_tool_call = self.check_tool_call_data(tool_candidate_data)

        # Process the tool call
        if is_this_a_tool_call:
            self.process_tool_calls(
                thread_id=thread_id, message_id=message_id,
                assistant_id=assistant_id, content=tool_candidate_data,
                run_id=run_id
            )

        logging_utility.info(
            "Processing conversation for thread_id: %s, run_id: %s, assistant_id: %s",
            thread_id, run_id, assistant_id
        )

        self.start_cancellation_listener(run_id)

        assistant = self.assistant_service.retrieve_assistant(assistant_id=assistant_id)

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

        try:
            response = requests.post(self.api_url, headers=self.headers, json=payload, stream=True, timeout=60)
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

                choices = chunk.get("choices", [])
                if not choices:
                    continue

                content_chunk = choices[0].get("delta", {}).get("content", "")

                if content_chunk:
                    assistant_reply += content_chunk
                    logging_utility.info("Yielding content chunk: %s", content_chunk)
                    yield json.dumps({'type': 'content', 'content': content_chunk})

        except Exception as e:
            logging_utility.error("[ERROR] Hyperbolic API streaming error: %s", str(e), exc_info=True)
            yield json.dumps({'type': 'error', 'content': '[ERROR] Hyperbolic API streaming error'})

        if assistant_reply:
            self.finalize_conversation(assistant_reply, thread_id, assistant_id, run_id)
