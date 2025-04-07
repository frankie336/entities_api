import json
import os
import sys
import time
from abc import ABC
from functools import lru_cache
from typing import Dict, Any, List

from dotenv import load_dotenv
from together import Together  # Using the official Together SDK

from entities_api.constants.assistant import PLATFORM_TOOLS
from entities_api.inference.base_inference import BaseInference
from entities_api.services.logging_service import LoggingUtility

load_dotenv()
logging_utility = LoggingUtility()


class TogetherV3Inference(BaseInference, ABC):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = Together(api_key=os.getenv("TOGETHER_API_KEY"))
        # LRU-cache for assistant and message retrieval
        self._assistant_cache = lru_cache(maxsize=32)(self._cache_assistant_retrieval)
        self._message_cache = lru_cache(maxsize=64)(self._cache_message_retrieval)
        self.tool_response = None
        self.function_call = None

    # state
    def set_tool_response_state(self, value):
        self.tool_response = value

    def get_tool_response_state(self):
        return self.tool_response

    def set_function_call_state(self, value):
        self.function_call = value

    def get_function_call_state(self):
        return self.function_call

    # Parsing
    def extract_tool_invocations(self, text: str) -> List[Dict[str, Any]]:
        return super().extract_tool_invocations(text)

    def parse_code_interpreter_partial(self, text):
        return super().parse_code_interpreter_partial(text)

    def ensure_valid_json(self, text: str):
        return super().ensure_valid_json(text)

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

    def _get_model_map(self, value):
        return super()._get_model_map(value)

    def _set_up_context_window(self, assistant_id, thread_id, trunk=True):
        return super()._set_up_context_window(assistant_id, thread_id, trunk=True)

    def finalize_conversation(self, assistant_reply, thread_id, assistant_id, run_id):
        return super().finalize_conversation(assistant_reply, thread_id, assistant_id, run_id)

    def _process_platform_tool_calls(self, thread_id, assistant_id, content, run_id):
        return super()._process_platform_tool_calls(thread_id, assistant_id, content, run_id)

    def _process_tool_calls(self, thread_id, assistant_id, content, run_id):
        return super()._process_tool_calls(thread_id, assistant_id, content, run_id)

    def stream_function_call_output(
        self, thread_id, run_id, assistant_id, model, stream_reasoning=False
    ):

        # TODO: experimenting with R1 function calling.
        model = "deepseek-ai/DeepSeek-R1"

        # if self._get_model_map(value=model):
        # model = self._get_model_map(value=model)

        self.start_cancellation_listener(run_id)

        # Send the assistant a reminder message about protocol
        # Create message and run
        self.message_service.create_message(
            thread_id=thread_id,
            assistant_id=assistant_id,
            content="give the user the output from tool as advised in system message",
            role="user",
        )

        logging_utility.info(
            "Sent the assistant a reminder message: %s",
        )

        request_payload = {
            "model": model,
            "messages": self._set_up_context_window(assistant_id, thread_id, trunk=True),
            "max_tokens": None,
            "temperature": 0.6,
            "top_p": 0.95,
            "top_k": 50,
            "repetition_penalty": 1,
            "stop": ["<｜end▁of▁sentence｜>"],
            "stream": True,
        }

        assistant_reply = ""
        reasoning_content = ""
        in_reasoning = False

        try:
            response = self.client.chat.completions.create(**request_payload)

            for token in response:
                if self.check_cancellation_flag():
                    logging_utility.warning(f"Run {run_id} cancelled mid-stream")
                    yield json.dumps({"type": "error", "content": "Run cancelled"})
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

                # Split the content based on <think> tags
                segments = self.REASONING_PATTERN.split(content)
                for seg in segments:
                    if not seg:
                        continue
                    if seg == "<think>":
                        in_reasoning = True
                        reasoning_content += seg
                        logging_utility.debug("Yielding reasoning tag: %s", seg)
                        yield json.dumps({"type": "reasoning", "content": seg})
                    elif seg == "</think>":
                        in_reasoning = False
                        reasoning_content += seg
                        logging_utility.debug("Yielding reasoning tag: %s", seg)
                        yield json.dumps({"type": "reasoning", "content": seg})
                    else:
                        if in_reasoning:
                            reasoning_content += seg
                            logging_utility.debug("Yielding reasoning segment: %s", seg)
                            yield json.dumps({"type": "reasoning", "content": seg})
                        else:
                            assistant_reply += seg
                            logging_utility.debug("Yielding content segment: %s", seg)
                            yield json.dumps({"type": "content", "content": seg})
                # Optional: slight pause to allow incremental delivery
                time.sleep(0.05)

        except Exception as e:
            error_msg = f"Together SDK error: {str(e)}"
            logging_utility.error(error_msg, exc_info=True)
            combined = reasoning_content + assistant_reply
            self.handle_error(combined, thread_id, assistant_id, run_id)
            yield json.dumps({"type": "error", "content": error_msg})
            return

        # Finalize conversation if there's any assistant reply content
        if assistant_reply:
            combined = reasoning_content + assistant_reply
            self.finalize_conversation(combined, thread_id, assistant_id, run_id)

    def stream_response(
        self, thread_id, message_id, run_id, assistant_id, model, stream_reasoning=False
    ):
        """
        Streams tool responses in real time using the TogetherAI SDK.
        - Yields each token chunk immediately, split by reasoning tags.
        - Accumulates the full response for final validation.
        - Supports mid-stream cancellation.
        - Strips markdown triple backticks from the final accumulated content.
        - Excludes all characters prior to (and including) the partial code-interpreter match.
        """
        request_payload = {
            "model": model,
            "messages": self._set_up_context_window(assistant_id, thread_id, trunk=True),
            "max_tokens": None,
            "temperature": 0.5,
            "top_p": 0.95,
            "top_k": 50,
            "repetition_penalty": 1,
            "stop": [""],
            "stream": True,
        }

        assistant_reply = ""
        accumulated_content = ""
        # Flags for code-mode
        code_mode = False
        code_buffer = ""
        # Flag for reasoning tag processing
        in_reasoning = False
        reasoning_content = ""

        try:
            response = self.client.chat.completions.create(**request_payload)

            for token in response:
                if self.check_cancellation_flag():
                    logging_utility.warning("Run %s cancelled mid-stream", run_id)
                    yield json.dumps({"type": "error", "content": "Run cancelled"})
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
                        full_match = partial_match.get("full_match")
                        if full_match:
                            match_index = accumulated_content.find(full_match)
                            if match_index != -1:
                                # Remove everything up to and including the full_match.
                                accumulated_content = accumulated_content[
                                    match_index + len(full_match) :
                                ]
                        # Enter code mode and initialize the code buffer with any remaining partial code.
                        code_mode = True
                        code_buffer = partial_match.get("code", "")
                        # Emit the start-of-code block marker.
                        yield json.dumps({"type": "hot_code", "content": "```python\n"})
                        # Do NOT yield code_buffer from the partial match.
                        continue

                # ---------------------------------------------------
                # 2) Already in code mode -> simply accumulate and yield token chunks
                # ---------------------------------------------------
                if code_mode:
                    code_buffer += content

                    # Split into lines while preserving order
                    while "\n" in code_buffer:
                        newline_pos = code_buffer.find("\n") + 1
                        line_chunk = code_buffer[:newline_pos]
                        code_buffer = code_buffer[newline_pos:]
                        yield json.dumps({"type": "hot_code", "content": line_chunk})
                        break

                    # Send remaining buffer if it exceeds threshold (100 chars)
                    if len(code_buffer) > 100:
                        yield json.dumps({"type": "hot_code", "content": code_buffer})
                        code_buffer = ""
                    continue

                # ---------------------------------------------------
                # 3) Process content using thinking tags (<think> and </think>)
                # ---------------------------------------------------
                segments = self.REASONING_PATTERN.split(content)
                for seg in segments:
                    if not seg:
                        continue
                    if seg == "<think>":
                        in_reasoning = True
                        reasoning_content += seg
                        logging_utility.debug("Yielding reasoning tag: %s", seg)
                        yield json.dumps({"type": "reasoning", "content": seg})
                    elif seg == "</think>":
                        in_reasoning = False
                        reasoning_content += seg
                        logging_utility.debug("Yielding reasoning tag: %s", seg)
                        yield json.dumps({"type": "reasoning", "content": seg})
                    else:
                        if in_reasoning:
                            reasoning_content += seg
                            logging_utility.debug("Yielding reasoning segment: %s", seg)
                            yield json.dumps({"type": "reasoning", "content": seg})
                        else:
                            assistant_reply += seg
                            logging_utility.debug("Yielding content segment: %s", seg)
                            yield json.dumps({"type": "content", "content": seg})
                # Optional: slight pause to allow incremental delivery
                time.sleep(0.01)

            # ---------------------------------------------------
            # 4) Validate if the accumulated response is a properly formed tool response.
            # ---------------------------------------------------
            json_accumulated_content = self.ensure_valid_json(text=accumulated_content)
            function_call = self.is_valid_function_call_response(json_data=json_accumulated_content)
            complex_vector_search = self.is_complex_vector_search(data=json_accumulated_content)

            if function_call or complex_vector_search:
                self.set_tool_response_state(True)
                self.set_function_call_state(json_accumulated_content)

            # ---------------------------------------------------
            # Deals with tool calls with preambles and or within
            # multi line text.
            # If a tool invocation is parsed from surrounding text,
            # and it has not already been dealt with.
            # ---------------------------------------------------
            tool_invocation_in_multi_line_text = self.extract_tool_invocations(
                text=accumulated_content
            )
            if tool_invocation_in_multi_line_text and not self.get_tool_response_state():
                self.set_tool_response_state(True)
                self.set_function_call_state(tool_invocation_in_multi_line_text[0])

            # Saves assistant's reply
            assistant_message = self.finalize_conversation(
                assistant_reply=str(accumulated_content),
                thread_id=thread_id,
                assistant_id=assistant_id,
                run_id=run_id,
            )
            logging_utility.info("Final accumulated content: %s", accumulated_content)
            # ---------------------------------------------------
            # Handle saving to vector store!
            # ---------------------------------------------------
            vector_store_id = self.get_vector_store_id_for_assistant(assistant_id=assistant_id)
            user_message = self.message_service.retrieve_message(message_id=message_id)
            self.vector_store_service.store_message_in_vector_store(
                message=user_message, vector_store_id=vector_store_id, role="user"
            )
            # ---------------------------------------------------
            # Avoid saving function call responses to the vector store
            # ---------------------------------------------------
            if not self.get_tool_response_state():
                self.vector_store_service.store_message_in_vector_store(
                    message=assistant_message, vector_store_id=vector_store_id, role="assistant"
                )

        except Exception as e:
            error_msg = f"Together SDK error: {str(e)}"
            logging_utility.error(error_msg, exc_info=True)
            self.handle_error(assistant_reply, thread_id, assistant_id, run_id)
            yield json.dumps({"type": "error", "content": error_msg})

    def process_conversation(
        self, thread_id, message_id, run_id, assistant_id, model, stream_reasoning=False
    ):

        if self._get_model_map(value=model):
            model = self._get_model_map(value=model)

        # ---------------------------------------------
        # Stream the response and yield each chunk.
        # --------------------------------------------
        for chunk in self.stream_response(
            thread_id, message_id, run_id, assistant_id, model, stream_reasoning
        ):
            yield chunk

        # print("The Tool response state is:")
        # print(self.get_tool_response_state())
        # print(self.get_function_call_state())
        if self.get_function_call_state():
            if self.get_function_call_state():
                if self.get_function_call_state().get("name") in PLATFORM_TOOLS:

                    self._process_platform_tool_calls(
                        thread_id=thread_id,
                        assistant_id=assistant_id,
                        content=self.get_function_call_state(),
                        run_id=run_id,
                    )

                    # Stream the output to the response:
                    for chunk in self.stream_function_call_output(
                        thread_id=thread_id, model=model, run_id=run_id, assistant_id=assistant_id
                    ):
                        yield chunk

        # Deal with user side function calls
        if self.get_function_call_state():
            if self.get_function_call_state():
                if self.get_function_call_state().get("name") not in PLATFORM_TOOLS:
                    self._process_tool_calls(
                        thread_id=thread_id,
                        assistant_id=assistant_id,
                        content=self.get_function_call_state(),
                        run_id=run_id,
                    )
                    # Stream the output to the response:
                    for chunk in self.stream_function_call_output(
                        thread_id=thread_id, run_id=run_id, assistant_id=assistant_id
                    ):
                        yield chunk


def __del__(self):
    """Cleanup resources."""
    super().__del__()
