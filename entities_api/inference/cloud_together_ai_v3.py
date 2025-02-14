import json
import re
import os
import sys
import time
from functools import lru_cache
from dotenv import load_dotenv
from together import Together  # Using the official Together SDK
from entities_api.clients.client_actions_client import ClientActionService
from entities_api.clients.client_run_client import ClientRunService
from entities_api.inference.base_inference import BaseInference
from entities_api.constants import PLATFORM_TOOLS
from entities_api.services.logging_service import LoggingUtility
from entities_api.platform_tools.platform_tool_service import PlatformToolService


load_dotenv()
logging_utility = LoggingUtility()


class TogetherV3Inference(BaseInference):
    # Use <think> tags for reasoning content
    REASONING_PATTERN = re.compile(r'(<think>|</think>)')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = Together(api_key=os.getenv("TOGETHER_API_KEY"))
        # LRU-cache for assistant and message retrieval
        self._assistant_cache = lru_cache(maxsize=32)(self._cache_assistant_retrieval)
        self._message_cache = lru_cache(maxsize=64)(self._cache_message_retrieval)

        self.tool_call_state = False

    def setup_services(self):
        """Initialize TogetherAI SDK."""
        logging_utility.info("TogetherAI SDK initialized")

    def _cache_assistant_retrieval(self, assistant_id):
        """LRU-cached assistant retrieval."""
        logging_utility.debug(f"Cache miss for assistant {assistant_id}")
        return self.assistant_service.retrieve_assistant(assistant_id=assistant_id)

    def _cache_message_retrieval(self, thread_id, system_message):
        """LRU-cached message retrieval."""
        return self.message_service.get_formatted_messages(thread_id, system_message=system_message)

    def normalize_roles(self, conversation_history):
        """Reuse parent class normalization."""
        return super().normalize_roles(conversation_history)

    def check_tool_call_data(self, input_string):
        """Regex to match the general structure of the string"""
        return super().check_tool_call_data(input_string)

    def is_valid_function_call_response(self, response: str) -> bool:
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

        :param response: JSON string representing a function call response.
        :return: True if valid, False otherwise.
        """
        try:
            data = json.loads(response.strip())  # Ensure it's a valid JSON object

            # Ensure required keys exist
            if not isinstance(data, dict) or "name" not in data or "arguments" not in data:
                return False

            # Validate "name" is a non-empty string
            if not isinstance(data["name"], str) or not data["name"].strip():
                return False

            # Validate "arguments" is a dictionary with at least one key-value pair
            if not isinstance(data["arguments"], dict) or not data["arguments"]:
                return False

            return True  # Passed all checks

        except (json.JSONDecodeError, TypeError):
            return False  # Invalid JSON or unexpected structure

    def parse_tools_calls(self, thread_id, message_id, run_id, assistant_id, model="deepseek-ai/DeepSeek-R1",
                          stream_reasoning=False):
        """
        Handles chat streaming using the TogetherAI SDK.
        - Uses the SDK for inference.
        - Accumulates full response before yielding.
        - Supports mid-stream cancellation.
        - Strips or escapes markdown triple backticks if present.
        """

        self.start_cancellation_listener(run_id)

        # Force correct model value
        model = "deepseek-ai/DeepSeek-V3"

        # Retrieve cached data
        assistant = self._assistant_cache(assistant_id)
        conversation_history = self._message_cache(thread_id, assistant.instructions)
        messages = self.normalize_roles(conversation_history)

        request_payload = {
            "model": model,
            "messages": [{"role": msg["role"], "content": msg["content"]} for msg in messages],
            "max_tokens": None,
            "temperature": 0.6,
            "top_p": 0.95,
            "top_k": 50,
            "repetition_penalty": 1,
            "stop": ["<｜end▁of▁sentence｜>"],
            "stream": True
        }

        assistant_reply = ""
        accumulated_content = ""
        start_checked = False

        try:
            response = self.client.chat.completions.create(**request_payload)

            for token in response:
                # Check for mid-stream cancellation before processing any tokens
                if self.check_cancellation_flag():
                    logging_utility.warning("Run %s cancelled mid-stream", run_id)
                    result = json.dumps({'type': 'error', 'content': 'Run cancelled'})
                    print(result)
                    return result

                if not hasattr(token, "choices") or not token.choices:
                    continue

                delta = token.choices[0].delta
                content = getattr(delta, "content", "")

                if not content:
                    continue

                # Accumulate content for early JSON validation
                accumulated_content += content

                # Validate JSON start after accumulating at least 2 non-whitespace characters
                if not start_checked and len(accumulated_content.strip()) >= 2:
                    start_checked = True

                    if not accumulated_content.strip().startswith(('```{', '{')):
                        logging_utility.warning(
                            "Early termination: Invalid JSON start detected in accumulated content: %s",
                            accumulated_content
                        )
                        #result = json.dumps({'type': 'error', 'content': accumulated_content})
                        print("EARLY EXIT!")
                        return False

                assistant_reply += content

            # **Handle potential markdown triple backticks**

            if accumulated_content.startswith("```") and accumulated_content.endswith("```"):
                logging_utility.info("Detected markdown-wrapped JSON. Stripping backticks.")
                accumulated_content = re.sub(r"^```|```$", "", accumulated_content).strip()

            # Log and sleep before returning final content
            logging_utility.info("Final accumulated content: %s", accumulated_content)

            is_this_a_tool_call = self.is_valid_function_call_response(accumulated_content)

            if is_this_a_tool_call:
                logging_utility.info("Validated tool response content: %s", accumulated_content)
                return accumulated_content
            else:
                return False

        except Exception as e:
            error_msg = f"Together SDK error: {str(e)}"
            logging_utility.error(error_msg, exc_info=True)
            self.handle_error(assistant_reply, thread_id, assistant_id, run_id)
            result = json.dumps({'type': 'error', 'content': error_msg})
            return result


    def process_platform_tool_calls(self, thread_id,
                           assistant_id, content,
                           run_id):

        # Save the assistants structured tool response
        self.message_service.save_assistant_message_chunk(
            thread_id=thread_id,
            content=content,
            role="assistant",
            assistant_id=assistant_id,
            sender_id=assistant_id,
            is_last_chunk=True
        )
        logging_utility.info("Saved triggering message to thread: %s", thread_id)

        try:
            content_dict = json.loads(content)

        except json.JSONDecodeError as e:
            logging_utility.error(f"Error decoding accumulated content: {e}")
            return

        # Creating action
        # Save the tool invocation for state management.
        action_service = ClientActionService()
        action = action_service.create_action(
            tool_name=content_dict["name"],
            run_id=run_id,
            function_args=content_dict["arguments"]
        )

        # Update run status to 'action_required'
        run_service = ClientRunService()
        run_service.update_run_status(run_id=run_id, new_status='action_required')
        logging_utility.info(f"Run {run_id} status updated to action_required")

        platform_tool_service = PlatformToolService()

        function_output = platform_tool_service.call_function(function_name=content_dict["name"],
                                                              arguments=content_dict["arguments"])

        if content_dict.get("name")=="code_interpreter":
            function_output = json.loads(function_output)
            output_value = function_output['result']['output']

            self.message_service.submit_tool_output(
                thread_id=thread_id,
                content=output_value,
                role="tool",
                assistant_id=assistant_id,
                tool_id="dummy"
            )

            self.action_service.update_action(action_id=action.id, status='completed')
            logging_utility.info(f"code interpreter tool output inserted!")

        return

    def stream_code_interpreter(self, thread_id, assistant_id, content, run_id):
        """
        Special case method to stream code_interpreter responses.
        Streams the code in real time as a markdown-formatted Python code block.
        """
        # Save the assistant's structured tool response
        self.message_service.save_assistant_message_chunk(
            thread_id=thread_id,
            content=content,
            role="assistant",
            assistant_id=assistant_id,
            sender_id=assistant_id,
            is_last_chunk=True
        )
        logging_utility.info("Saved triggering message to thread: %s", thread_id)

        try:
            content_dict = json.loads(content)
        except json.JSONDecodeError as e:
            logging_utility.error(f"Error decoding accumulated content: {e}")
            return

        tool_name = content_dict.get("name")
        function_args = content_dict.get("arguments", {})
        code = function_args.get("code", "")

        # Start streaming: yield the opening markdown for a Python code block.
        opening = "```python\n"
        logging_utility.info("Streaming code block start: %s", opening.strip())
        yield opening

        # Stream the code line by line.
        for line in code.split("\n"):
            # Log each line
            logging_utility.info(f"Streaming code chunk: {line}")
            # Yield the line with a newline appended for proper formatting.
            yield line + "\n"
            time.sleep(0.1)  # Simulate delay for real-time effect

        # End streaming: yield the closing markdown backticks.
        closing = "```"
        logging_utility.info("Streaming code block end: %s", closing)
        yield closing

        # Continue with the rest of the platform tool call logic if needed.
        # For example, creating actions and updating run status:
        action_service = ClientActionService()
        action_service.create_action(
            tool_name=tool_name,
            run_id=run_id,
            function_args=function_args
        )

        run_service = ClientRunService()
        run_service.update_run_status(run_id=run_id, new_status='action_required')
        logging_utility.info(f"Run {run_id} status updated to action_required")

        platform_tool_service = PlatformToolService()
        handle_function = platform_tool_service.call_function(
            function_name=tool_name,
            arguments=function_args
        )

        # Optionally, yield the execution result or log it.
        result_message = f"\nExecution Result:\n{handle_function}"
        logging_utility.info("Streaming execution result: %s", result_message.strip())
        yield result_message

    def process_tool_calls(self, thread_id,
                           assistant_id, content,
                           run_id):

        self.message_service.save_assistant_message_chunk(
            thread_id=thread_id,
            content=content,
            role="assistant",
            assistant_id=assistant_id,
            sender_id=assistant_id,
            is_last_chunk=True
        )
        logging_utility.info("Saved triggering message to thread: %s", thread_id)



        try:
            content_dict = json.loads(content)
        except json.JSONDecodeError as e:
            logging_utility.error(f"Error decoding accumulated content: {e}")
            return

        # Creating action
        # Save the tool invocation for state management.
        action_service = ClientActionService()
        action_service.create_action(
            tool_name=content_dict["name"],
            run_id=run_id,
            function_args=content_dict["arguments"]
        )

        # Update run status to 'action_required'
        run_service = ClientRunService()
        run_service.update_run_status(run_id=run_id, new_status='action_required')
        logging_utility.info(f"Run {run_id} status updated to action_required")

        # Now wait for the run's status to change from 'action_required'.
        while True:
            run = self.run_service.retrieve_run(run_id)
            if run.status != "action_required":
                break
            time.sleep(1)

        logging_utility.info("Action status transition complete. Reprocessing conversation.")

        # Continue processing the conversation transparently.
        # (Rebuild the conversation history if needed; here we re-use deepseek_messages.)

        logging_utility.info("No tool call triggered; proceeding with conversation.")

        return content  # Return the accumulated content

    def process_conversation(self, thread_id, message_id, run_id, assistant_id,
                             model="deepseek-ai/DeepSeek-R1", stream_reasoning=False):
        """
        Handles chat streaming using the TogetherAI SDK.
        - Uses the SDK for inference.
        - Splits the streamed content on <think> and </think> markers.
        - Yields each segment immediately with its type.
        - Supports mid-stream cancellation.
        """
        # Force correct model value
        model = "deepseek-ai/DeepSeek-V3"

        # Parse the tool response structured data.
        tool_candidate_data = self.parse_tools_calls(
            thread_id=thread_id,
            message_id=message_id,
            assistant_id=assistant_id,
            run_id=run_id,
            model=model
        )

        if tool_candidate_data and self.is_valid_function_call_response(tool_candidate_data):
            tool_response_to_json = json.loads(tool_candidate_data)
            tool_name = tool_response_to_json.get('name')

            if tool_name in PLATFORM_TOOLS:
                # If it's the code_interpreter, stream the code first.
                if tool_name == "code_interpreter":
                    for seg in self.stream_code_interpreter(
                            thread_id=thread_id,
                            assistant_id=assistant_id,
                            content=tool_candidate_data,
                            run_id=run_id):
                        yield json.dumps({'type': 'content', 'content': seg})
                    # Process code interpreter tool call.
                    self.process_platform_tool_calls(
                        thread_id=thread_id,
                        assistant_id=assistant_id,
                        content=tool_candidate_data,
                        run_id=run_id
                    )
                else:
                    # For other platform tools, process as ordinary tool calls.
                    self.process_tool_calls(
                        thread_id=thread_id,
                        assistant_id=assistant_id,
                        content=tool_candidate_data,
                        run_id=run_id
                    )
                    logging_utility.info("Tool call detected; proceeding accordingly.")
            else:
                print("Not a platform tool")

        # Begin conversation processing.
        self.start_cancellation_listener(run_id)
        assistant = self._assistant_cache(assistant_id)
        conversation_history = self.message_service.get_formatted_messages(
            thread_id, system_message=assistant.instructions
        )
        conversation_history = self.normalize_roles(conversation_history)
        messages = [{"role": msg['role'], "content": msg['content']} for msg in conversation_history]

        request_payload = {
            "model": model,
            "messages": messages,
            "max_tokens": None,
            "temperature": 0.6,
            "top_p": 0.95,
            "top_k": 50,
            "repetition_penalty": 1,
            "stop": ["<｜end▁of▁sentence｜>"],
            "stream": True
        }

        assistant_reply = ""
        reasoning_content = ""
        in_reasoning = False

        try:
            response = self.client.chat.completions.create(**request_payload)
            for token in response:
                if self.check_cancellation_flag():
                    logging_utility.warning(f"Run {run_id} cancelled mid-stream")
                    yield json.dumps({'type': 'error', 'content': 'Run cancelled'})
                    break

                if not hasattr(token, "choices") or not token.choices:
                    continue

                delta = token.choices[0].delta
                content = getattr(delta, "content", "")
                if not content:
                    continue

                # Print raw content for debugging.
                sys.stdout.write(content)
                sys.stdout.flush()

                # Split content based on <think> tags.
                segments = self.REASONING_PATTERN.split(content)
                for seg in segments:
                    if not seg:
                        continue
                    if seg == "<think>":
                        in_reasoning = True
                        reasoning_content += seg
                        logging_utility.debug("Yielding reasoning tag: %s", seg)
                        yield json.dumps({'type': 'reasoning', 'content': seg})
                    elif seg == "</think>":
                        in_reasoning = False
                        reasoning_content += seg
                        logging_utility.debug("Yielding reasoning tag: %s", seg)
                        yield json.dumps({'type': 'reasoning', 'content': seg})
                    else:
                        if in_reasoning:
                            reasoning_content += seg
                            logging_utility.debug("Yielding reasoning segment: %s", seg)
                            yield json.dumps({'type': 'reasoning', 'content': seg})
                        else:
                            assistant_reply += seg
                            logging_utility.debug("Yielding content segment: %s", seg)
                            yield json.dumps({'type': 'content', 'content': seg})
                time.sleep(0.01)

        except Exception as e:
            error_msg = f"Together SDK error: {str(e)}"
            logging_utility.error(error_msg, exc_info=True)
            combined = reasoning_content + assistant_reply
            self.handle_error(combined, thread_id, assistant_id, run_id)
            yield json.dumps({'type': 'error', 'content': error_msg})
            return

        if assistant_reply:
            combined = reasoning_content + assistant_reply
            self.finalize_conversation(combined, thread_id, assistant_id, run_id)

    def __del__(self):
        """Cleanup resources."""
        super().__del__()
