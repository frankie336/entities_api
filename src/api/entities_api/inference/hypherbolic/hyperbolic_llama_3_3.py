import json
import os
import sys
import time
from abc import ABC
from typing import Any, Generator, Optional

from dotenv import load_dotenv
from projectdavid_common import ValidationInterface
from projectdavid_common.utilities.logging_service import LoggingUtility

from entities_api.inference.base_inference import BaseInference

load_dotenv()
logging_utility = LoggingUtility()


class HyperbolicLlama33Inference(BaseInference, ABC):

    def setup_services(self):
        logging_utility.debug(
            "HyperbolicDeepSeekV3Inference specific setup completed (if any)."
        )

    def stream_function_call_output(
        self,
        thread_id,
        run_id,
        assistant_id,
        model,
        stream,
        name=None,
        stream_reasoning=False,
        api_key: Optional[str] = None,
    ):

        return super().stream_function_call_output(
            thread_id=thread_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            stream=self.stream,
            stream_reasoning=stream_reasoning,
            api_key=api_key,
        )

    def stream(
        self,
        thread_id: str,
        message_id: str,
        run_id: str,
        assistant_id: str,
        model: Any,
        stream_reasoning: bool = True,
        api_key: Optional[str] = None,
    ) -> Generator[str, None, None]:

        self.start_cancellation_listener(run_id)

        if self._get_model_map(value=model):
            model = self._get_model_map(value=model)

        request_payload = {
            "model": model,
            "messages": self._set_up_context_window(
                assistant_id, thread_id, trunk=True
            ),
            "max_tokens": None,
            "temperature": 0.6,
            "stream": True,
        }

        assistant_reply = ""
        accumulated_content = ""
        code_mode = False
        code_buffer = ""

        try:

            client_to_use = self._get_openai_client(
                base_url=os.getenv("HYPERBOLIC_BASE_URL"), api_key=api_key
            )

            response = client_to_use.chat.completions.create(**request_payload)

            for token in response:
                if self.check_cancellation_flag():
                    logging_utility.warning(f"Run {run_id} cancelled mid-stream")
                    yield json.dumps({"type": "error", "content": "Run cancelled"})
                    break

                if not hasattr(token, "choices") or not token.choices:
                    continue

                delta = token.choices[0].delta
                delta_content = getattr(delta, "content", "")
                if not delta_content:
                    continue

                sys.stdout.write(delta_content)
                sys.stdout.flush()

                segments = [delta_content]

                for seg in segments:
                    if not seg:
                        continue

                    assistant_reply += seg
                    accumulated_content += seg

                    # --- Code Interpreter Trigger Check ---
                    partial_match = self.parse_code_interpreter_partial(
                        accumulated_content
                    )

                    if not code_mode and partial_match:
                        full_match = partial_match.get("full_match")
                        if full_match:
                            match_index = accumulated_content.find(full_match)
                            if match_index != -1:
                                accumulated_content = accumulated_content[
                                    match_index + len(full_match) :
                                ]
                        code_mode = True
                        code_buffer = partial_match.get("code", "")
                        self.code_mode = True
                        yield json.dumps({"type": "hot_code", "content": "```python\n"})
                        continue

                    if code_mode:
                        results, code_buffer = self._process_code_interpreter_chunks(
                            seg, code_buffer
                        )
                        for r in results:
                            yield r
                            assistant_reply += r
                        continue

                    if not code_buffer:
                        yield json.dumps({"type": "content", "content": seg}) + "\n"

                time.sleep(0.05)

        except Exception as e:
            error_msg = f"Llama 3 / Hyperbolic SDK error: {str(e)}"
            logging_utility.error(error_msg, exc_info=True)
            self.handle_error(assistant_reply, thread_id, assistant_id, run_id)
            yield json.dumps({"type": "error", "content": error_msg})
            return

        # Finalize assistant message and parse function calls
        if assistant_reply:
            self.finalize_conversation(assistant_reply, thread_id, assistant_id, run_id)

        if accumulated_content:
            self.parse_and_set_function_calls(accumulated_content, assistant_reply)
            logging_utility.info(f"Function call parsing completed for run {run_id}")

        self.run_service.update_run_status(
            run_id, ValidationInterface.StatusEnum.completed
        )

    def process_function_calls(
        self,
        thread_id,
        run_id,
        assistant_id,
        model=None,
        api_key: Optional[str] = None,
    ):

        return super().process_function_calls(
            thread_id=thread_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            api_key=api_key,
        )

    def process_conversation(
        self,
        thread_id,
        message_id,
        run_id,
        assistant_id,
        model,
        stream_reasoning=False,
        api_key: Optional[str] = None,
    ):
        """
        Processes the conversation, passing the api_key down for use
        in the actual API request via override.
        """

        if self._get_model_map(value=model):
            model = self._get_model_map(value=model)

        logging_utility.info(
            f"Processing conversation for run {run_id} with model {model}. API key provided: {'Yes' if api_key else 'No'}"
        )

        for chunk in self.stream(
            thread_id=thread_id,
            message_id=message_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            stream_reasoning=stream_reasoning,
            api_key=api_key,
        ):
            yield chunk

        fc_state = self.get_function_call_state()

        # Process function calls, passing the api_key if needed by sub-calls
        for chunk in self.process_function_calls(
            thread_id=thread_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            api_key=api_key,
        ):
            yield chunk

        logging_utility.info(
            f"Finished processing conversation generator for run {run_id}"
        )

        if fc_state:
            for chunk in self.stream(
                thread_id=thread_id,
                message_id=message_id,
                run_id=run_id,
                assistant_id=assistant_id,
                model=model,
                stream_reasoning=stream_reasoning,
                api_key=api_key,
            ):
                yield chunk
