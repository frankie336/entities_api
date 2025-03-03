import json
import sys
import time

from dotenv import load_dotenv
from openai import OpenAI

from entities_api.constants.assistant import PLATFORM_TOOLS
from entities_api.inference.base_inference import BaseInference
from entities_api.services.logging_service import LoggingUtility

load_dotenv()
logging_utility = LoggingUtility()

class HyperbolicR1Inference(BaseInference):
    def setup_services(self):
        """
        Initialize the DeepSeek client and other services.
        """
        self.deepseek_client = OpenAI(
            api_key="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJwcmltZS50aGFub3MzMzZAZ21haWwuY29tIiwiaWF0IjoxNzM4NDc2MzgyfQ.4V27eTb-TRwPKcA5zit4pJckoEUEa7kxmHwFEn9kwTQ",
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


        self.start_cancellation_listener(run_id)

        # Force correct model value
        if self._get_model_map(value=model):
            model = self._get_model_map(value=model)
        else:
            model = "deepseek-ai/DeepSeek-R1"


        request_payload = {
            "model": model,
            "messages": self._set_up_context_window(assistant_id, thread_id, trunk=True) ,
            "max_tokens": None,
            "temperature": 0.6,
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
                # Optional: slight pause to allow incremental delivery
                time.sleep(0.01)

        except Exception as e:
            error_msg = f"Together SDK error: {str(e)}"
            logging_utility.error(error_msg, exc_info=True)
            combined = reasoning_content + assistant_reply
            self.handle_error(combined, thread_id, assistant_id, run_id)
            yield json.dumps({'type': 'error', 'content': error_msg})
            return

        # Finalize conversation if there's any assistant reply content
        if assistant_reply:
            combined = reasoning_content + assistant_reply
            self.finalize_conversation(combined, thread_id, assistant_id, run_id)


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
