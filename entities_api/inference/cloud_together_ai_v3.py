import json
import re
import os
import sys
import time
import threading
from functools import lru_cache
from dotenv import load_dotenv
from together import Together  # Using the official Together SDK

from entities_api import code_interpreter
from entities_api.clients.client_actions_client import ClientActionService
from entities_api.clients.client_run_client import ClientRunService
from entities_api.inference.base_inference import BaseInference
from entities_api.constants import PLATFORM_TOOLS
from entities_api.services.logging_service import LoggingUtility
from entities_api.platform_tools.platform_tool_service import PlatformToolService


load_dotenv()
logging_utility = LoggingUtility()



code_interpreter_response = False

class TogetherV3Inference(BaseInference):
    # Use <think> tags for reasoning content
    REASONING_PATTERN = re.compile(r'(<think>|</think>)')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = Together(api_key=os.getenv("TOGETHER_API_KEY"))
        # LRU-cache for assistant and message retrieval
        self._assistant_cache = lru_cache(maxsize=32)(self._cache_assistant_retrieval)
        self._message_cache = lru_cache(maxsize=64)(self._cache_message_retrieval)
        self.tool_response = None
        self.function_call = None


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

    def is_valid_function_call_response(self, json_data):
        """Regex to match the general structure of the string"""
        return super().is_valid_function_call_response(json_data)

    # state
    def set_tool_response_state(self, value):
        self.tool_response = value

    def get_tool_response_state(self):
        return self.tool_response


    def set_function_call_state(self, value):
        self.function_call = value

    def get_function_call_state(self):
        return self.function_call


    @staticmethod
    def detect_code_interpreter(accumulated_content):
        """
        Detects if the accumulated content starts with a code_interpreter tool call.
        Handles markdown wrapping, whitespace, and partial matches.
        """
        # Strip leading/trailing whitespace
        stripped_content = accumulated_content.strip()

        # Handle markdown triple backticks
        if stripped_content.startswith("```") and stripped_content.endswith("```"):
            stripped_content = re.sub(r"^```|```$", "", stripped_content).strip()

        # Check for partial or full match of the JSON structure
        if stripped_content.startswith(('{"name":"code_interpreter"', '```{"name":"code_interpreter"')):
            logging_utility.debug("CODE DETECTED!")
            return True

        # Case-insensitive check for robustness
        if stripped_content.lower().startswith(('{"name":"code_interpreter"', '```{"name":"code_interpreter"')):
            logging_utility.debug("CODE DETECTED (case-insensitive)!")
            return True

        # Partial match for early detection
        if '{"name":"code_interpreter"' in stripped_content:
            logging_utility.debug("Partial match detected. Waiting for more content...")
            return False

        logging_utility.debug("No match detected.")
        return False

    def stream_response(self, thread_id, message_id, run_id, assistant_id,
                             model="deepseek-ai/DeepSeek-R1", stream_reasoning=False):
        """
        Streams tool responses in real time using the TogetherAI SDK.
        - Yields each token chunk immediately, split by reasoning tags.
        - Accumulates the full response for final validation.
        - Supports mid-stream cancellation.
        - Strips markdown triple backticks from the final accumulated content.
        """
        # Force correct model version
        model = "deepseek-ai/DeepSeek-V3"

        self.start_cancellation_listener(run_id)

        # Retrieve cached data and normalize conversation history
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
        reasoning_content = ""
        in_reasoning = False
        start_checked = False

        try:
            response = self.client.chat.completions.create(**request_payload)

            for token in response:
                if self.check_cancellation_flag():
                    logging_utility.warning("Run %s cancelled mid-stream", run_id)
                    yield json.dumps({'type': 'error', 'content': 'Run cancelled'})
                    break

                if not hasattr(token, "choices") or not token.choices:
                    continue

                delta = token.choices[0].delta
                content = getattr(delta, "content", "")
                if not content:
                    continue

                # Print raw content for debugging
                sys.stdout.write(content)
                sys.stdout.flush()

                # Accumulate full content for final validation.
                accumulated_content += content

                # Validate JSON start after accumulating at least 2 non-whitespace characters.
                if not start_checked and len(accumulated_content.strip()) >= 2:
                    start_checked = True
                    if not accumulated_content.strip().startswith(('```{', '{')):
                        logging_utility.warning(
                            "Early termination: Invalid JSON start detected in accumulated content: %s",
                            accumulated_content)
                        yield json.dumps({'type': 'error', 'content': accumulated_content})
                        #return

                # Split content using the reasoning pattern.
                # Assumes self.REASONING_PATTERN is defined as a compiled regex.
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

            # After streaming, remove markdown triple backticks if present.
            if accumulated_content.startswith("```") and accumulated_content.endswith("```"):
                logging_utility.info("Detected markdown-wrapped JSON. Stripping backticks.")
                accumulated_content = re.sub(r"^```json|```$", "", accumulated_content).strip()
                accumulated_content = json.loads(accumulated_content)


            # Validate if the  accumulated response is a properly formed tool response.
            if self.is_valid_function_call_response(json_data=accumulated_content):
                # At the stage if we know the assistants response is a valid tool call
                # We invoke dependent logic.
                self.set_tool_response_state(True)
                self.set_function_call_state(accumulated_content)


            logging_utility.info("Final accumulated content: %s", accumulated_content)


        except Exception as e:
            error_msg = f"Together SDK error: {str(e)}"
            logging_utility.error(error_msg, exc_info=True)
            self.handle_error(assistant_reply, thread_id, assistant_id, run_id)
            yield json.dumps({'type': 'error', 'content': error_msg})

        if assistant_reply:
            combined = reasoning_content + assistant_reply
            self.finalize_conversation(combined, thread_id, assistant_id, run_id)


    def stream_tool_output_response(self, thread_id, message_id, run_id, assistant_id,
                             model="deepseek-ai/DeepSeek-R1", stream_reasoning=False):

        """
                Streams tool responses in real time using the TogetherAI SDK.
                - Yields each token chunk immediately, split by reasoning tags.
                - Accumulates the full response for final validation.
                - Supports mid-stream cancellation.
                - Strips markdown triple backticks from the final accumulated content.
                """
        # Force correct model version
        model = "deepseek-ai/DeepSeek-V3"

        self.start_cancellation_listener(run_id)

        # Retrieve cached data and normalize conversation history
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
        reasoning_content = ""
        in_reasoning = False
        start_checked = False

        try:
            response = self.client.chat.completions.create(**request_payload)

            for token in response:
                if self.check_cancellation_flag():
                    logging_utility.warning("Run %s cancelled mid-stream", run_id)
                    yield json.dumps({'type': 'error', 'content': 'Run cancelled'})
                    break

                if not hasattr(token, "choices") or not token.choices:
                    continue

                delta = token.choices[0].delta
                content = getattr(delta, "content", "")
                if not content:
                    continue

                # Print raw content for debugging
                sys.stdout.write(content)
                sys.stdout.flush()

                # Accumulate full content for final validation.
                accumulated_content += content

                # Validate JSON start after accumulating at least 2 non-whitespace characters.
                if not start_checked and len(accumulated_content.strip()) >= 2:
                    start_checked = True
                    if not accumulated_content.strip().startswith(('```{', '{')):
                        logging_utility.warning(
                            "Early termination: Invalid JSON start detected in accumulated content: %s",
                            accumulated_content)
                        yield json.dumps({'type': 'error', 'content': accumulated_content})
                        # return

                # Split content using the reasoning pattern.
                # Assumes self.REASONING_PATTERN is defined as a compiled regex.
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

            logging_utility.info("Final accumulated content: %s", accumulated_content)


        except Exception as e:
            error_msg = f"Together SDK error: {str(e)}"
            logging_utility.error(error_msg, exc_info=True)
            self.handle_error(assistant_reply, thread_id, assistant_id, run_id)
            yield json.dumps({'type': 'error', 'content': error_msg})

        if assistant_reply:
            combined = reasoning_content + assistant_reply
            self.finalize_conversation(combined, thread_id, assistant_id, run_id)


    def parse_tools_calls(self, thread_id, message_id, run_id, assistant_id,
                          model="deepseek-ai/DeepSeek-R1", stream_reasoning=False):
        """
        Handles chat streaming using the TogetherAI SDK.
        - Uses the SDK for inference.
        - Accumulates full response before yielding.
        - Supports mid-stream cancellation.
        - Strips or escapes markdown triple backticks if present.

        Once the code_interpreter is detected, it continuously attempts to parse the
        accumulated JSON. If successful, it extracts the "code" field, wraps it in a
        Markdown code block (with Python markup), and yields that formatted content.
        """
        self.code_interpreter_response = True  # Initially set to False

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
            "repetition_penalty": 1.2,
            "stop": ["<｜end▁of▁sentence｜>"],
            "stream": True
        }

        assistant_reply = ""
        accumulated_content = ""
        start_checked = False
        streaming_triggered = False  # Flag indicating that a code_interpreter response was detected
        last_yield_index = 0  # Index to track what portion has already been sent

        try:
            response = self.client.chat.completions.create(**request_payload)

            for token in response:
                if self.check_cancellation_flag():
                    logging_utility.warning("Run %s cancelled mid-stream", run_id)
                    result = json.dumps({'type': 'error', 'content': 'Run cancelled'})
                    return result

                if not hasattr(token, "choices") or not token.choices:
                    continue

                delta = token.choices[0].delta
                content = getattr(delta, "content", "")
                if not content:
                    continue

                # Append the new content to the accumulator.
                accumulated_content += content

                # Check if this is a code_interpreter response.
                if self.detect_code_interpreter(accumulated_content):
                    if not streaming_triggered:
                        streaming_triggered = True
                        # Create and start async thread for state change
                        def set_code_interpreter_state():
                            self.code_interpreter_response = True
                            logging_utility.info("Code interpreter detected. Streaming response...")

                        state_thread = threading.Thread(target=set_code_interpreter_state)
                        state_thread.start()
                    # Attempt to parse the accumulated content as JSON.
                    formatted = None
                    try:
                        full_response = json.loads(accumulated_content)
                        # Expect structure: {"name": "code_interpreter", "arguments": {"code": "..."}}
                        if (full_response.get("arguments") and
                                full_response["arguments"].get("code")):
                            code = full_response["arguments"]["code"]
                            formatted = "```python\n" + code + "\n```"
                        else:
                            formatted = accumulated_content  # Fallback if structure not as expected
                    except Exception as e:
                        # Likely incomplete JSON; use the raw accumulated content.
                        formatted = accumulated_content

                    # Only yield the new portion since the last yield.
                    new_chunk = formatted[last_yield_index:]
                    if new_chunk:
                        yield json.dumps({'type': 'code_interpreter_stream', 'content': new_chunk})
                        last_yield_index = len(formatted)

                assistant_reply += content

            # Once streaming ends, clean up markdown if needed.
            if accumulated_content.startswith("```") and accumulated_content.endswith("```"):
                logging_utility.info("Detected markdown-wrapped JSON. Stripping backticks.")
                accumulated_content = re.sub(r"^```|```$", "", accumulated_content).strip()
                accumulated_content = json.loads(accumulated_content).strip()


            logging_utility.info("Final accumulated content: %s", accumulated_content)
            is_valid = self.is_valid_function_call_response(accumulated_content)
            if is_valid:
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



    def parse_tools_calls_normal(self, thread_id, message_id, run_id, assistant_id, model="deepseek-ai/DeepSeek-R1",
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

        # Creating action
        # Save the tool invocation for state management.
        action_service = ClientActionService()
        action = action_service.create_action(
            tool_name=content["name"],
            run_id=run_id,
            function_args=content["arguments"]
        )

        # Update run status to 'action_required'
        run_service = ClientRunService()
        run_service.update_run_status(run_id=run_id, new_status='action_required')
        logging_utility.info(f"Run {run_id} status updated to action_required")
        platform_tool_service = PlatformToolService()
        function_output = platform_tool_service.call_function(function_name=content["name"],
                                                              arguments=content["arguments"])

        if content.get("name")=="code_interpreter":
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

    def process_conversation(self, thread_id, message_id, run_id, assistant_id,
                             model="deepseek-ai/DeepSeek-R1", stream_reasoning=False):
        # There is a model name clash in the LLM router, so forcing the name here.
        model = "deepseek-ai/DeepSeek-V3"

        # Stream the response and yield each chunk.
        for chunk in self.stream_response(thread_id, message_id, run_id, assistant_id, model, stream_reasoning):
            yield chunk

        print("The Tool response state is:")
        print(self.get_tool_response_state())
        print(self.get_function_call_state())

        if self.get_function_call_state():
            if self.get_function_call_state():
                self.process_platform_tool_calls(
                    thread_id=thread_id,
                    assistant_id=assistant_id,
                    content=self.get_function_call_state(),
                    run_id=run_id

                )
                # Stream the output to the response:
                for chunk in self.stream_tool_output_response(thread_id, message_id, run_id, assistant_id, model, stream_reasoning):
                    yield chunk
                self.stream_tool_output_response(
                    thread_id=thread_id,
                    message_id=message_id,
                    assistant_id=assistant_id,
                    model=model,
                    run_id=run_id,

                )


    def __del__(self):
        """Cleanup resources."""
        super().__del__()
