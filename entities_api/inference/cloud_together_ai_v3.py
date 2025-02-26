import json
import os
import sys
import time
from datetime import date
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
        return super().set_tool_response_state(value=value)

    def get_tool_response_state(self):
        return super().get_tool_response_state()

    def set_function_call_state(self, value):
        return super().set_function_call_state(value=value)

    def get_function_call_state(self):
        return super().get_function_call_state()

    def extract_function_candidates(self, text):
        """
        Extracts potential JSON function call patterns from arbitrary text positions.
        Handles cases where function calls are embedded within other content.
        """
        return super().extract_function_candidates(text=text)


    def ensure_valid_json(self, text: str):
        """
        Ensures the accumulated tool response is in valid JSON format.
        - Fixes incorrect single quotes (`'`) → double quotes (`"`)
        - Ensures proper key formatting
        - Removes trailing commas if present
        """
        return super().ensure_valid_json(text=text)

    def normalize_content(self, content):
        """Smart format normalization with fallback"""
        return super().normalize_content(content=content)

    def validate_and_set(self, content):
        """Core validation pipeline"""
        return super().validate_and_set(content=content)

    def get_vector_store_id_for_assistant(self, assistant_id: str, store_suffix: str = "chat") -> str:
        """
        Retrieve the vector store ID for a specific assistant and store suffix.

        Args:
            assistant_id (str): The ID of the assistant.
            store_suffix (str): The suffix of the vector store name (default: "chat").

        Returns:
            str: The collection name of the vector store.
        """
        return super().get_vector_store_id_for_assistant(assistant_id=assistant_id, store_suffix=store_suffix)

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

        # Fetch the assistant's tools
        tools = self.tool_service.list_tools(assistant_id=assistant.id, restructure=True)

        # Get today's date
        today = date.today()

        conversation_history = self.message_service.get_formatted_messages(
            thread_id, system_message="tools:" + str(tools) + assistant.instructions + f"Today's date:, {str(today)}"
        )
        messages = self.normalize_roles(conversation_history)

        # Sliding Windows Truncation
        truncated_message = self.conversation_truncator.truncate(messages)

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

        assistant_reply = ""  # This will store the full assistant response
        accumulated_content = ""
        code_mode = False
        code_buffer = ""
        # Initialize reasoning variables
        in_reasoning = False
        reasoning_content = ""

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

                # Optionally, print the raw content for debugging
                sys.stdout.write(content)
                sys.stdout.flush()

                # Append the raw content to our accumulator
                accumulated_content += content

                # Handle Partial Code Interpreter Match
                if not code_mode:
                    partial_match = self.parse_code_interpreter_partial(accumulated_content)
                    if partial_match:
                        full_match = partial_match.get('full_match')
                        if full_match:
                            match_index = accumulated_content.find(full_match)
                            if match_index != -1:
                                accumulated_content = accumulated_content[match_index + len(full_match):]
                        code_mode = True
                        code_buffer = partial_match.get('code', '')
                        yield json.dumps({'type': 'hot_code', 'content': '```python\n'})
                        continue

                if code_mode:
                    code_buffer += content
                    while '\n' in code_buffer:
                        newline_pos = code_buffer.find('\n') + 1
                        line_chunk = code_buffer[:newline_pos]
                        code_buffer = code_buffer[newline_pos:]
                        yield json.dumps({'type': 'hot_code', 'content': line_chunk})
                        break

                    if len(code_buffer) > 100:
                        yield json.dumps({'type': 'hot_code', 'content': code_buffer})
                        code_buffer = ""
                    continue

                # Process reasoning content if streaming reasoning is enabled
                if stream_reasoning:
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
                else:
                    assistant_reply += content
                    yield json.dumps({'type': 'content', 'content': content}) + '\n'

            vector_store_id = self.get_vector_store_id_for_assistant(assistant_id=assistant_id)

            # Save the assistant's response to the main db
            if assistant_reply:
                message = self.finalize_conversation(assistant_reply, thread_id, assistant_id, run_id)
                logging_utility.info("Final accumulated content: %s", assistant_reply)

                # -----------------------
                # Save the assistant's response to the vector store for memory recall
                # -----------------------
                self.vector_store_service.store_message_in_vector_store(
                    message=message,
                    vector_store_id=vector_store_id
                )

            # Final Processing
            accumulated_content = self.ensure_valid_json(str(accumulated_content))
            assistant_reply = self.ensure_valid_json(str(assistant_reply))  # Ensure full response is validated
            normalized = self.normalize_content(accumulated_content)

            # Finds function calls embedded within surrounding text
            if not self.validate_and_set(normalized):
                for candidate in self.extract_function_candidates(normalized):
                    if self.validate_and_set(candidate):
                        break
                else:
                    if legacy_match := self.parse_nested_function_call_json(json.dumps(accumulated_content)):
                        self.set_tool_response_state(True)
                        self.set_function_call_state(legacy_match)

            # --------------------------------------
            # Save the user's message to vector store
            # --------------------------------------
            message = self.message_service.retrieve_message(message_id=message_id)
            self.vector_store_service.store_message_in_vector_store(
                message=message,
                vector_store_id=vector_store_id
            )

        except Exception as e:
            error_msg = f"Together SDK error: {str(e)}"
            logging_utility.error(error_msg, exc_info=True)
            self.handle_error(assistant_reply or '', thread_id, assistant_id, run_id)
            yield json.dumps({'type': 'error', 'content': error_msg})


    def stream_function_call_response(self, thread_id, run_id, assistant_id,
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

                    for chunk in self.stream_function_call_response(thread_id=thread_id,
                                                                    run_id=run_id,
                                                                    assistant_id=assistant_id
                                                                    ):
                        yield chunk

        #-----------------------------------
        # User tools are function calls
        # defined by API users.
        # Deal with user side function calls
        # -----------------------------------
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
                    for chunk in self.stream_function_call_response(thread_id=thread_id,
                                                                    run_id=run_id,
                                                                    assistant_id=assistant_id                                         ):
                        yield chunk


    def __del__(self):
        """Cleanup resources."""
        super().__del__()
