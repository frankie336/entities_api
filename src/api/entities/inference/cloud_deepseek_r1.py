import json
import time
import os

from dotenv import load_dotenv
from openai import OpenAI

from entities.constants.assistant import PLATFORM_TOOLS
from entities.inference.base_inference import BaseInference
from entities.services.logging_service import LoggingUtility

load_dotenv()
logging_utility = LoggingUtility()



class DeepSeekR1Cloud(BaseInference):
    def setup_services(self):
        """
        Initialize the DeepSeek client and other services.
        """
        self.deepseek_client = OpenAI(
            api_key=os.getenv('DEEP_SEEK_API_KEY'),
            base_url="https://api.deepseek.com"
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


    def stream_response(self, thread_id, message_id, run_id, assistant_id,
                        model, stream_reasoning=True):


        """
        Process conversation with dual streaming (content + reasoning). If a tool call trigger
        is detected, update run status to 'action_required', then wait for the status to change,
        and reprocess the original prompt.
        """
        logging_utility.info(
            "Processing conversation for thread_id: %s, run_id: %s, assistant_id: %s",
            thread_id, run_id, assistant_id
        )

        try:
            stream_response = self.deepseek_client.chat.completions.create(
                model=model,
                messages=self._set_up_context_window(assistant_id, thread_id, trunk=True),
                stream=True,
                temperature=0.6,
                # tools=tools
            )

            assistant_reply = ""
            accumulated_content = ""
            reasoning_content = ""
            code_mode = False
            code_buffer = ""

            for chunk in stream_response:
                logging_utility.debug("Raw chunk received: %s", chunk)

                # Process reasoning tokens as before.
                reasoning_chunk = getattr(chunk.choices[0].delta, 'reasoning_content', '')
                if reasoning_chunk:
                    reasoning_content += reasoning_chunk
                    yield json.dumps({
                        'type': 'reasoning',
                        'content': reasoning_chunk
                    })

                # Process content tokens with code-mode logic.
                content_chunk = getattr(chunk.choices[0].delta, 'content', '')
                if content_chunk:
                    # Always accumulate the full content.
                    assistant_reply += content_chunk
                    accumulated_content += content_chunk

                    # ---------------------------------------------------
                    # 1) Check for partial code-interpreter match and exclude prior characters
                    # ---------------------------------------------------
                    if not code_mode:
                        partial_match = self.parse_code_interpreter_partial(accumulated_content)
                        if partial_match:
                            full_match = partial_match.get('full_match')
                            if full_match:
                                match_index = accumulated_content.find(full_match)
                                if match_index != -1:
                                    # Remove everything up to and including the full_match.
                                    accumulated_content = accumulated_content[match_index + len(full_match):]
                            # Enter code mode and initialize the code buffer with any remaining partial code.
                            code_mode = True
                            code_buffer = partial_match.get('code', '')
                            # Emit the start-of-code block marker.
                            yield json.dumps({'type': 'hot_code', 'content': '```python\n'})
                            # Do NOT yield the code_buffer from the partial match.
                            continue

                    # ---------------------------------------------------
                    # 2) Already in code mode -> simply accumulate and yield code chunks
                    # ---------------------------------------------------
                    if code_mode:
                        code_buffer += content_chunk
                        while "\n" in code_buffer:
                            newline_pos = code_buffer.find("\n") + 1
                            line_chunk = code_buffer[:newline_pos]
                            code_buffer = code_buffer[newline_pos:]
                            yield json.dumps({'type': 'hot_code', 'content': line_chunk})
                            break
                        if len(code_buffer) > 100:
                            yield json.dumps({'type': 'hot_code', 'content': code_buffer})
                            code_buffer = ""
                        continue

                    # If not in code mode, yield content as normal.
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
            # Saves assistant's reply
            assistant_message = self.finalize_conversation(
                assistant_reply=assistant_reply,
                thread_id=thread_id,
                assistant_id=assistant_id,
                run_id=run_id
            )
            logging_utility.info("Assistant response stored successfully.")

            # ---------------------------------------------------
            # Handle saving to vector store!
            # ---------------------------------------------------
            vector_store_id = self.get_vector_store_id_for_assistant(assistant_id=assistant_id)
            user_message = self.message_service.retrieve_message(message_id=message_id)
            self.vector_store_service.store_message_in_vector_store(
                message=user_message,
                vector_store_id=vector_store_id,
                role="user"
            )

            # ---------------------------------------------------
            # Avoid saving function call responses to the vector store
            # ---------------------------------------------------
            if not self.get_tool_response_state():
                self.vector_store_service.store_message_in_vector_store(
                    message=assistant_message,
                    vector_store_id=vector_store_id,
                    role="assistant"
                )

        # ---------------------------------------------------
        # 3) Validate if the accumulated response is a properly formed tool response.
        # ---------------------------------------------------
        if accumulated_content:
            json_accumulated_content = self.ensure_valid_json(text=accumulated_content)
            function_call = self.is_valid_function_call_response(json_data=json_accumulated_content)
            complex_vector_search = self.is_complex_vector_search(data=json_accumulated_content)

            if function_call or complex_vector_search:
                self.set_tool_response_state(True)
                self.set_function_call_state(json_accumulated_content)

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

        #print("The Tool response state is:")
        #print(self.get_tool_response_state())
        #print(self.get_function_call_state())

        if self.get_function_call_state():
            if self.get_function_call_state():
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

















