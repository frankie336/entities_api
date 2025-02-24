import json
import os
import sys
import time
from functools import lru_cache

from dotenv import load_dotenv
from together import Together

from entities_api.constants.assistant import PLATFORM_TOOLS
from entities_api.inference.base_inference import BaseInference
from entities_api.services.logging_service import LoggingUtility

load_dotenv()
logging_utility = LoggingUtility()


class TogetherV3Inference(BaseInference):

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

    def parse_nested_function_call_json(self, text):
        """
        Parses a JSON-like string with a nested object structure and variable keys,
        supporting both single and double quotes, as well as multiline values.

        Expected pattern:
        {
            <quote>first_key<quote> : <quote>first_value<quote>,
            <quote>second_key<quote> : {
                <quote>nested_key<quote> : <quote>nested_value<quote>
            }
        }
        """
        return super().parse_nested_function_call_json(text)

    def parse_code_interpreter_partial(self, text):
        """
        Parses a partial JSON-like string that begins with:
        {'name': 'code_interpreter', 'arguments': {'code':

        It captures everything following the 'code': marker.
        Note: Because the input is partial, the captured code may be incomplete.

        Returns:
            A dictionary with the key 'code' containing the extracted text,
            or None if no match is found.
        """
        return super().parse_code_interpreter_partial(text)


    def set_tool_response_state(self, value):
        self.tool_response = value

    def get_tool_response_state(self):
        return self.tool_response


    def set_function_call_state(self, value):
        self.function_call = value

    def get_function_call_state(self):
        return self.function_call

    def stream_response(self, thread_id, message_id, run_id, assistant_id,
                        model="deepseek-ai/DeepSeek-R1", stream_reasoning=False):
        """
        Streams tool responses in real time using the TogetherAI SDK.
        - Yields each token chunk immediately, split by reasoning tags.
        - Accumulates the full response for final validation.
        - Supports mid-stream cancellation.
        - Strips markdown triple backticks from the final accumulated content.
        - Excludes all characters prior to (and including) the partial code-interpreter match.
        """
        # Force correct model version
        model = "deepseek-ai/DeepSeek-V3"
        self.start_cancellation_listener(run_id)

        # Retrieve cached data and normalize conversation history
        assistant = self._assistant_cache(assistant_id)

        # Fetch the assistants tools
        tools = self.tool_service.list_tools(assistant_id=assistant.id, restructure=True)

        # ---------------------------------------------------
        # Some inference points do not support a tools  definition
        # in the api payload thus we inject tool definition into
        # the system message.
        # ---------------------------------------------------

        conversation_history = self.message_service.get_formatted_messages(
            thread_id, system_message= "tools:" + str(tools) + assistant.instructions
        )
        messages = self.normalize_roles(conversation_history)

        #Sliding Windows Truncation
        truncated_message = self.conversation_truncator.truncate(messages)
        #print(truncated_message)


        request_payload = {
            "model": model,
            "messages": truncated_message,
            "max_tokens": None,
            "temperature": 0.5,
            "top_p": 0.95,
            "top_k": 50,
            "repetition_penalty": 1,
            "stop": [""],
            "stream": True
        }

        assistant_reply = ""
        accumulated_content = ""
        # Flags for code-mode
        code_mode = False
        code_buffer = ""

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

                # Write raw content for debugging
                sys.stdout.write(content)
                sys.stdout.flush()

                # Accumulate the full content
                accumulated_content += content

                # ---------------------------------------------------
                # 1) Check for partial code-interpreter match and exclude prior characters
                # ---------------------------------------------------
                if not code_mode:
                    partial_match = self.parse_code_interpreter_partial(accumulated_content)
                    if partial_match:
                        # Remove the matched portion from accumulated_content.
                        full_match = partial_match.get('full_match')
                        if full_match:
                            match_index = accumulated_content.find(full_match)
                            if match_index != -1:
                                # Remove everything up to and including the full_match.
                                accumulated_content = accumulated_content[match_index + len(full_match):]
                        # Alternatively, if no full_match is provided, you could clear accumulated_content:
                        # else:
                        #     accumulated_content = ""

                        # Enter code mode and initialize the code buffer with any remaining partial code.
                        code_mode = True
                        code_buffer = partial_match.get('code', '')
                        # Emit the start-of-code block marker.
                        yield json.dumps({'type': 'hot_code', 'content': '```python\n'})
                        # Do NOT yield code_buffer from the partial match.
                        continue

                # ---------------------------------------------------
                # 2) Already in code mode -> simply accumulate and yield token_count
                # ---------------------------------------------------
                if code_mode:
                    code_buffer += content

                    # Split into lines while preserving order
                    while '\n' in code_buffer:
                        newline_pos = code_buffer.find('\n') + 1
                        line_chunk = code_buffer[:newline_pos]
                        code_buffer = code_buffer[newline_pos:]
                        yield json.dumps({'type': 'hot_code', 'content': line_chunk})

                        break

                    # Send remaining buffer if it exceeds threshold (100 chars)
                    if len(code_buffer) > 100:
                        yield json.dumps({'type': 'hot_code', 'content': code_buffer})
                        code_buffer = ""
                    continue

                if not code_mode:
                    yield json.dumps({'type': 'content', 'content': content}) + '\n'
                else:
                    yield json.dumps({'type': 'content', 'content': content}) + '\n'

            # ---------------------------------------------------
            # 3) Validate if the accumulated response is a properly formed tool response.
            # ---------------------------------------------------
            code_interpreter_function_call = self.parse_nested_function_call_json(text=accumulated_content)

            if code_interpreter_function_call:
                accumulated_content = json.loads(accumulated_content)

                print(accumulated_content)
                time.sleep(1000)

                self.set_tool_response_state(True)
                self.set_function_call_state(accumulated_content)

            json_accumulated_content = json.loads(accumulated_content)

            is_function_call = self.is_valid_function_call_response(json_data=json_accumulated_content)
            if is_function_call:
                self.set_tool_response_state(True)
                self.set_function_call_state(json_accumulated_content)

            # Saves assistant's reply
            self.finalize_conversation(
                assistant_reply=str(accumulated_content),
                thread_id=thread_id,
                assistant_id=assistant_id,
                run_id=run_id
            )
            logging_utility.info("Final accumulated content: %s", accumulated_content)

        except Exception as e:
            error_msg = f"Together SDK error: {str(e)}"
            logging_utility.error(error_msg, exc_info=True)
            self.handle_error(assistant_reply, thread_id, assistant_id, run_id)
            yield json.dumps({'type': 'error', 'content': error_msg})

        if assistant_reply:
            self.finalize_conversation(assistant_reply, thread_id, assistant_id, run_id)

    def stream_function_call_output(self, thread_id, run_id, assistant_id,
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

        # Send the assistant a reminder message about protocol
        # Create message and run
        self.message_service.create_message(
            thread_id=thread_id,
            assistant_id=assistant_id,
            content='give the user the output from tool as advised in system message',
            role='user',
        )
        logging_utility.info("Sent the assistant a reminder message: %s", )


        # Retrieve cached data and normalize conversation history
        assistant = self._assistant_cache(assistant_id)
        conversation_history = self.message_service.get_formatted_messages(
            thread_id, system_message=assistant.instructions
        )
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
                yield json.dumps({'type': 'content', 'content': content})
                assistant_reply += content
                # Print raw content for debugging
                #sys.stdout.write(content)
                #sys.stdout.flush()

                # Accumulate full content for final validation.
                accumulated_content += content

            logging_utility.info("Final accumulated content: %s", accumulated_content)


        except Exception as e:
            error_msg = f"Together SDK error: {str(e)}"
            logging_utility.error(error_msg, exc_info=True)
            self.handle_error(assistant_reply, thread_id, assistant_id, run_id)
            yield json.dumps({'type': 'error', 'content': error_msg})

        if assistant_reply:
            self.finalize_conversation(assistant_reply, thread_id, assistant_id, run_id)

    def process_tool_calls(self, thread_id,
                           assistant_id, content,
                           run_id):

        return super().process_tool_calls(thread_id=thread_id, assistant_id=assistant_id,
                                          content=content, run_id=run_id
                                          )

    def process_platform_tool_calls(self, thread_id, assistant_id, content, run_id):
        """Process platform tool calls with enhanced logging and error handling."""

        return super().process_platform_tool_calls(
            thread_id=thread_id, assistant_id=assistant_id, content=content, run_id=run_id
        )


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
                if self.get_function_call_state().get("name") in PLATFORM_TOOLS:

                    self.process_platform_tool_calls(
                        thread_id=thread_id,
                        assistant_id=assistant_id,
                        content=self.get_function_call_state(),
                        run_id=run_id

                    )

                    for chunk in self.stream_function_call_output(thread_id=thread_id,
                                                                  run_id=run_id,
                                                                  assistant_id=assistant_id
                                                                  ):
                        yield chunk

        #Deal with user side function calls
        if self.get_function_call_state():
            if self.get_function_call_state():
                if self.get_function_call_state().get("name") not in PLATFORM_TOOLS:
                    self.process_tool_calls(
                        thread_id=thread_id,
                        assistant_id=assistant_id,
                        content=self.get_function_call_state(),
                        run_id=run_id
                    )
                    # Stream the output to the response:
                    for chunk in self.stream_function_call_output(thread_id=thread_id,
                                                                  run_id=run_id,
                                                                  assistant_id=assistant_id
                                                                  ):
                        yield chunk


    def __del__(self):
        """Cleanup resources."""
        super().__del__()
