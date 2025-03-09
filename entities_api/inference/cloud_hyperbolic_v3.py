import json
import sys
import time
import os
from typing import Dict, Any, List

from dotenv import load_dotenv
from openai import OpenAI

from entities_api.constants.assistant import PLATFORM_TOOLS
from entities_api.inference.base_inference import BaseInference
from entities_api.services.logging_service import LoggingUtility

load_dotenv()
logging_utility = LoggingUtility()

class HyperbolicV3Inference(BaseInference):
    def setup_services(self):
        """
        Initialize the DeepSeek client and other services.
        """
        self.deepseek_client = OpenAI(
            api_key=os.getenv("HYPERBOLIC_API_KEY"),
            base_url="https://api.hyperbolic.xyz/v1"
        )
        logging_utility.info("DeepSeekV3Cloud specific setup completed.")


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


    def _set_up_context_window(self, assistant_id, thread_id, trunk=True):
        return super()._set_up_context_window(assistant_id, thread_id, trunk=True)

    def finalize_conversation(self, assistant_reply, thread_id, assistant_id, run_id):
        return super().finalize_conversation(assistant_reply, thread_id, assistant_id, run_id)

    def _process_platform_tool_calls(self, thread_id, assistant_id, content, run_id):
        return super()._process_platform_tool_calls(thread_id, assistant_id, content, run_id)

    def _process_tool_calls(self, thread_id,
                            assistant_id, content,
                            run_id):
        return super()._process_tool_calls(thread_id, assistant_id, content, run_id)


    def stream_function_call_output(self, thread_id, run_id, assistant_id,
                                    model, stream_reasoning=False):

        logging_utility.info(
            "Processing conversation for thread_id: %s, run_id: %s, assistant_id: %s",
            thread_id, run_id, assistant_id
        )


        # Send the assistant a reminder message about protocol
        # Create message and run

        self.message_service.create_message(
            thread_id=thread_id,
            assistant_id=assistant_id,
            content='give the user the output from tool as advised in system message',
            role='user',
        )

        logging_utility.info("Sent the assistant a reminder message: %s", )




        try:
            stream_response = self.deepseek_client.chat.completions.create(
                model=model,
                messages=self._set_up_context_window(assistant_id, thread_id, trunk=True),
                stream=True,
                temperature=0.6
            )

            assistant_reply = ""
            accumulated_content = ""
            reasoning_content = ""

            for chunk in stream_response:
                logging_utility.debug("Raw chunk received: %s", chunk)
                reasoning_chunk = getattr(chunk.choices[0].delta, 'reasoning_content', '')

                if reasoning_chunk:
                    reasoning_content += reasoning_chunk
                    yield json.dumps({
                        'type': 'reasoning',
                        'content': reasoning_chunk
                    })

                content_chunk = getattr(chunk.choices[0].delta, 'content', '')
                if content_chunk:
                    assistant_reply += content_chunk
                    accumulated_content += content_chunk
                    yield json.dumps({'type': 'content', 'content': content_chunk}) + '\n'

                time.sleep(0.01)

        except Exception as e:
            error_msg = "[ERROR] DeepSeek API streaming error"
            logging_utility.error(f"{error_msg}: {str(e)}", exc_info=True)
            yield json.dumps({
                'type': 'error',
                'content': error_msg
            })
            return

        if assistant_reply:
            assistant_message = self.finalize_conversation(
                assistant_reply=assistant_reply,
                thread_id=thread_id,
                assistant_id=assistant_id,
                run_id=run_id
            )
            logging_utility.info("Assistant response stored successfully.")

        self.run_service.update_run_status(run_id, "completed")
        if reasoning_content:
            logging_utility.info("Final reasoning content: %s", reasoning_content)

    def _process_code_chunks(self, content_chunk, code_buffer):
        """
        Process code chunks while in code mode.

        Appends the incoming content_chunk to code_buffer,
        then extracts a single line (if a newline exists) and handles buffer overflow.

        Returns:
            tuple: (results, updated code_buffer)
                - results: list of JSON strings representing code chunks.
                - updated code_buffer: the remaining buffer content.
        """
        forbidden_functions = ['os.system', 'subprocess.run', 'eval', 'exec']
        results = []
        code_buffer += content_chunk

        # Process one line at a time if a newline is present.
        if "\n" in code_buffer:
            newline_pos = code_buffer.find("\n") + 1
            line_chunk = code_buffer[:newline_pos]
            code_buffer = code_buffer[newline_pos:]
            # Optionally, you can add security checks here for forbidden patterns.
            results.append(json.dumps({'type': 'hot_code', 'content': line_chunk}))

        # Buffer overflow protection: if the code_buffer grows too large,
        # yield its content as a chunk and reset it.
        if len(code_buffer) > 100:
            results.append(json.dumps({'type': 'hot_code', 'content': code_buffer}))
            code_buffer = ""

        return results, code_buffer

    def stream_response(self, thread_id, message_id, run_id, assistant_id, model, stream_reasoning=True):
        """
        Process conversation with dual streaming of content and reasoning.
        If a tool call trigger is detected, update run status to 'action_required',
        then wait for the status change and reprocess the original prompt.

        This function splits incoming tokens into reasoning and content segments
        (using <think> tags) while also handling a code mode. When a partial
        code-interpreter match is found, it enters code mode, processes and streams
        raw code via the _process_code_chunks helper, and emits a start-of-code marker.

        Accumulated content is later used to finalize the conversation and validate
        tool responses.
        """
        # Start cancellation listener
        self.start_cancellation_listener(run_id)

        # Force correct model value via mapping (defaulting if not mapped)
        if self._get_model_map(value=model):
            model = self._get_model_map(value=model)
        else:
            pass
            # model = "deepseek-ai/DeepSeek-R1"

        request_payload = {
            "model": model,
            "messages": self._set_up_context_window(assistant_id, thread_id, trunk=True),
            "max_tokens": None,
            "temperature": 0.6,
            "stream": True
        }

        assistant_reply = ""
        accumulated_content = ""
        reasoning_content = ""
        in_reasoning = False
        code_mode = False
        code_buffer = ""

        try:
            # Using self.client for streaming responses; adjust if deepseek_client is required.
            response = self.client.chat.completions.create(**request_payload)

            for token in response:
                if self.check_cancellation_flag():
                    logging_utility.warning(f"Run {run_id} cancelled mid-stream")
                    yield json.dumps({'type': 'error', 'content': 'Run cancelled'})
                    break

                if not hasattr(token, "choices") or not token.choices:
                    continue

                delta = token.choices[0].delta

                # Process any explicit reasoning content from delta.
                delta_reasoning = getattr(delta, "reasoning_content", "")
                if delta_reasoning:
                    reasoning_content += delta_reasoning
                    yield json.dumps({'type': 'reasoning', 'content': delta_reasoning})

                # Process content from delta.
                delta_content = getattr(delta, "content", "")
                if not delta_content:
                    continue

                # Optionally output raw content for debugging.
                sys.stdout.write(delta_content)
                sys.stdout.flush()

                # Split the content based on reasoning tags (<think> and </think>)
                segments = self.REASONING_PATTERN.split(delta_content) if hasattr(self, 'REASONING_PATTERN') else [
                    delta_content]
                for seg in segments:
                    if not seg:
                        continue

                    # Check for reasoning start/end tags.
                    if seg == "<think>":
                        in_reasoning = True
                        reasoning_content += seg
                        logging_utility.debug("Yielding reasoning tag: %s", seg)
                        yield json.dumps({'type': 'reasoning', 'content': seg})
                        continue
                    elif seg == "</think>":
                        in_reasoning = False
                        reasoning_content += seg
                        logging_utility.debug("Yielding reasoning tag: %s", seg)
                        yield json.dumps({'type': 'reasoning', 'content': seg})
                        continue

                    if in_reasoning:
                        # If within reasoning, yield as reasoning content.
                        reasoning_content += seg
                        logging_utility.debug("Yielding reasoning segment: %s", seg)
                        yield json.dumps({'type': 'reasoning', 'content': seg})
                    else:
                        # Outside reasoning: process as normal content.
                        assistant_reply += seg
                        accumulated_content += seg
                        logging_utility.debug("Processing content segment: %s", seg)

                        # Check if a code-interpreter trigger is found (and not already in code mode).
                        if not code_mode:
                            partial_match = self.parse_code_interpreter_partial(accumulated_content)
                            if partial_match:
                                full_match = partial_match.get('full_match')
                                if full_match:
                                    match_index = accumulated_content.find(full_match)
                                    if match_index != -1:
                                        # Remove all content up to and including the trigger.
                                        accumulated_content = accumulated_content[match_index + len(full_match):]
                                code_mode = True
                                code_buffer = partial_match.get('code', '')
                                # Emit start-of-code block marker.
                                yield json.dumps({'type': 'hot_code', 'content': '```python\n'})

                                continue  # Skip further processing of this segment.

                        # If already in code mode, delegate to code-chunk processing.
                        if code_mode:
                            results, code_buffer = self._process_code_chunks(seg, code_buffer)
                            for r in results:
                                yield r  # Yield raw code line(s).
                                assistant_reply += r  # Optionally accumulate the code.
                            continue

                        # Yield non-code content as normal.
                        yield json.dumps({'type': 'content', 'content': seg}) + '\n'

                # Slight pause to allow incremental delivery.
                time.sleep(0.05)

        except Exception as e:
            error_msg = f"Together SDK error: {str(e)}"
            logging_utility.error(error_msg, exc_info=True)
            combined = reasoning_content + assistant_reply
            self.handle_error(combined, thread_id, assistant_id, run_id)
            yield json.dumps({'type': 'error', 'content': error_msg})
            return

        # Finalize conversation if there's any assistant reply content.
        if assistant_reply:
            combined = reasoning_content + assistant_reply
            self.finalize_conversation(combined, thread_id, assistant_id, run_id)

        # Validate the accumulated content for proper tool response structure.
        if accumulated_content:
            json_accumulated_content = self.ensure_valid_json(text=accumulated_content)
            function_call = self.is_valid_function_call_response(json_data=json_accumulated_content)
            complex_vector_search = self.is_complex_vector_search(data=json_accumulated_content)
            if function_call or complex_vector_search:
                self.set_tool_response_state(True)
                self.set_function_call_state(json_accumulated_content)
            tool_invocation_in_multi_line_text = self.extract_tool_invocations(text=accumulated_content)
            if tool_invocation_in_multi_line_text and not self.get_tool_response_state():
                self.set_tool_response_state(True)
                self.set_function_call_state(tool_invocation_in_multi_line_text[0])

        self.run_service.update_run_status(run_id, "completed")
        if reasoning_content:
            logging_utility.info("Final reasoning content: %s", reasoning_content)

    def process_conversation(self, thread_id, message_id, run_id, assistant_id,
                             model, stream_reasoning=False):


        if self._get_model_map(value=model):
            model = self._get_model_map(value=model)

        # ---------------------------------------------
        # Stream the response and yield each chunk.
        # --------------------------------------------
        for chunk in self.stream_response(thread_id, message_id, run_id, assistant_id, model, stream_reasoning):
            yield chunk

        if self.get_function_call_state():
            if self.get_function_call_state():

                print("The Tool response state is:")
                print(self.get_tool_response_state())
                print(self.get_function_call_state())
                #time.sleep(1000)

                if self.get_function_call_state().get("name") in PLATFORM_TOOLS:

                    self._process_platform_tool_calls(
                        thread_id=thread_id,
                        assistant_id=assistant_id,
                        content=self.get_function_call_state(),
                        run_id=run_id

                    )

                    # Stream the output to the response:
                    for chunk in self.stream_function_call_output(thread_id=thread_id,
                                                                  run_id=run_id,
                                                                  model=model,
                                                                  assistant_id=assistant_id
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
