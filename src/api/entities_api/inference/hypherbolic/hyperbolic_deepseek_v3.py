import json
import os
from abc import ABC
from typing import Any, Generator, Optional

from dotenv import load_dotenv
from projectdavid_common import ValidationInterface
from projectdavid_common.utilities.logging_service import LoggingUtility

from entities_api.dependencies import get_redis
from entities_api.inference.base_inference import BaseInference

load_dotenv()
logging_utility = LoggingUtility()


class HyperbolicDeepSeekV3Inference(BaseInference, ABC):

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

    def _shunt_to_redis_stream(
        self, redis, stream_key, chunk_dict, *, maxlen=1000, ttl_seconds=3600
    ):
        return super()._shunt_to_redis_stream(
            redis, stream_key, chunk_dict, maxlen=maxlen, ttl_seconds=ttl_seconds
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

        import re  # ensure regex is available here

        redis = get_redis()
        stream_key = f"stream:{run_id}"

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

        client_to_use = None
        key_source_log = "default configured"

        if api_key:
            key_source_log = "provided"
            logging_utility.debug(
                f"Run {run_id}: Creating temporary Hyperbolic client with provided API key."
            )
            hyperbolic_base_url = os.getenv("HYPERBOLIC_BASE_URL")
            if not hyperbolic_base_url:
                logging_utility.error(
                    f"Run {run_id}: Configuration Error: 'HYPERBOLIC_BASE_URL' is not set."
                )
                chunk = {
                    "type": "error",
                    "content": "Server misconfiguration: Hyperbolic endpoint missing.",
                }
                yield json.dumps(chunk)
                self._shunt_to_redis_stream(redis, stream_key, chunk)
                return
            try:
                client_to_use = self._get_openai_client(
                    base_url=hyperbolic_base_url, api_key=api_key
                )
            except Exception as e:
                logging_utility.error(
                    f"Run {run_id}: Failed to init Hyperbolic client: {e}",
                    exc_info=True,
                )
                chunk = {"type": "error", "content": f"Client init error: {e}"}
                yield json.dumps(chunk)
                self._shunt_to_redis_stream(redis, stream_key, chunk)
                return

        if not client_to_use:
            logging_utility.error(f"Run {run_id}: No Hyperbolic client available.")
            chunk = {"type": "error", "content": "Hyperbolic client error."}
            yield json.dumps(chunk)
            self._shunt_to_redis_stream(redis, stream_key, chunk)
            return

        assistant_reply = ""
        accumulated_content = ""
        reasoning_content = ""
        in_reasoning = False
        in_function_call = False
        code_mode = False
        code_buffer = ""

        try:
            response = client_to_use.chat.completions.create(**request_payload)

            for token in response:
                if self.check_cancellation_flag():
                    logging_utility.warning(f"Run {run_id} cancelled mid-stream")
                    chunk = {"type": "error", "content": "Run cancelled"}
                    yield json.dumps(chunk)
                    self._shunt_to_redis_stream(redis, stream_key, chunk)
                    break

                if not getattr(token, "choices", None):
                    continue

                delta = token.choices[0].delta

                # 1) stream reasoning_content from delta if present
                delta_reasoning = getattr(delta, "reasoning_content", "")
                if delta_reasoning and stream_reasoning:
                    reasoning_content += delta_reasoning
                    chunk = {"type": "reasoning", "content": delta_reasoning}
                    yield json.dumps(chunk)
                    self._shunt_to_redis_stream(redis, stream_key, chunk)

                delta_content = getattr(delta, "content", "")
                if not delta_content:
                    continue

                # 2) split on both reasoning and function‐call tags
                segments = re.split(r"(<think>|</think>|<fc>|</fc>)", delta_content)

                for seg in segments:
                    if not seg:
                        continue

                    # reasoning tag open
                    if seg == "<think>":
                        in_reasoning = True
                        if stream_reasoning:
                            chunk = {"type": "reasoning", "content": seg}
                            yield json.dumps(chunk)
                            self._shunt_to_redis_stream(redis, stream_key, chunk)
                        continue

                    # reasoning tag close
                    if seg == "</think>":
                        in_reasoning = False
                        if stream_reasoning:
                            chunk = {"type": "reasoning", "content": seg}
                            yield json.dumps(chunk)
                            self._shunt_to_redis_stream(redis, stream_key, chunk)
                        continue

                    # function‐call tag open
                    if seg == "<fc>":
                        in_function_call = True
                        continue

                    # function‐call tag close
                    if seg == "</fc>":
                        in_function_call = False
                        continue

                    # fallback: detect untagged function‐call JSON
                    if not in_function_call:
                        try:
                            candidate = json.loads(seg.strip())
                            if self.is_valid_function_call_response(candidate):
                                in_function_call = True
                                assistant_reply += seg
                                accumulated_content += seg
                                logging_utility.debug(
                                    f"Emitting function_call chunk (fallback): {seg.strip()}"
                                )
                                self._shunt_to_redis_stream(
                                    redis,
                                    stream_key,
                                    {"type": "function_call", "content": seg},
                                )
                                in_function_call = False
                                continue
                        except Exception:
                            pass

                    # inside a function‐call: accumulate only
                    if in_function_call:
                        assistant_reply += seg
                        accumulated_content += seg
                        logging_utility.debug(
                            f"Emitting function_call chunk: {seg.strip()}"
                        )
                        self._shunt_to_redis_stream(
                            redis, stream_key, {"type": "function_call", "content": seg}
                        )
                        continue

                    # within reasoning text
                    if in_reasoning:
                        reasoning_content += seg
                        if stream_reasoning:
                            chunk = {"type": "reasoning", "content": seg}
                            yield json.dumps(chunk)
                            self._shunt_to_redis_stream(redis, stream_key, chunk)
                        continue

                    # normal/code text
                    assistant_reply += seg
                    accumulated_content += seg

                    # detect code‐interpreter partials
                    partial = getattr(self, "parse_code_interpreter_partial", None)
                    partial_match = partial(accumulated_content) if partial else None

                    if not code_mode and partial_match:
                        full = partial_match.get("full_match")
                        if full:
                            idx = accumulated_content.find(full)
                            if idx != -1:
                                accumulated_content = accumulated_content[
                                    idx + len(full) :
                                ]
                        code_mode = True
                        code_buffer = partial_match.get("code", "")
                        self.code_mode = True
                        chunk = {"type": "hot_code", "content": "```python\n"}
                        yield json.dumps(chunk)
                        self._shunt_to_redis_stream(redis, stream_key, chunk)
                        if code_buffer and hasattr(
                            self, "_process_code_interpreter_chunks"
                        ):
                            results, code_buffer = (
                                self._process_code_interpreter_chunks("", code_buffer)
                            )
                            for r in results:
                                yield r
                                self._shunt_to_redis_stream(redis, stream_key, r)
                                assistant_reply += (
                                    r
                                    if isinstance(r, str)
                                    else json.loads(r).get("content", "")
                                )
                        continue

                    if code_mode:
                        if hasattr(self, "_process_code_interpreter_chunks"):
                            results, code_buffer = (
                                self._process_code_interpreter_chunks(seg, code_buffer)
                            )
                            for r in results:
                                yield r
                                self._shunt_to_redis_stream(redis, stream_key, r)
                                assistant_reply += (
                                    r
                                    if isinstance(r, str)
                                    else json.loads(r).get("content", "")
                                )
                        else:
                            chunk = {"type": "hot_code", "content": seg}
                            yield json.dumps(chunk)
                            self._shunt_to_redis_stream(redis, stream_key, chunk)
                        continue

                    # plain content
                    if not code_buffer:
                        chunk = {"type": "content", "content": seg}
                        yield json.dumps(chunk)
                        self._shunt_to_redis_stream(redis, stream_key, chunk)

        except Exception as e:
            error_msg = f"Hyperbolic SDK error (using {key_source_log} key): {e}"
            logging_utility.error(f"Run {run_id}: {error_msg}", exc_info=True)
            if hasattr(self, "handle_error"):
                self.handle_error(
                    reasoning_content + assistant_reply, thread_id, assistant_id, run_id
                )
            chunk = {"type": "error", "content": error_msg}
            yield json.dumps(chunk)
            self._shunt_to_redis_stream(redis, stream_key, chunk)
            return

        # finalize conversation
        if assistant_reply and hasattr(self, "finalize_conversation"):
            self.finalize_conversation(
                reasoning_content + assistant_reply, thread_id, assistant_id, run_id
            )

        # detect pending function calls
        if accumulated_content and hasattr(self, "parse_and_set_function_calls"):
            function_call = self.parse_and_set_function_calls(
                accumulated_content, assistant_reply
            )
        else:
            function_call = False

        if function_call:
            self.run_service.update_run_status(
                run_id, ValidationInterface.StatusEnum.pending_action
            )

        if hasattr(self, "run_service") and hasattr(ValidationInterface, "StatusEnum"):
            if not self.get_function_call_state():
                self.run_service.update_run_status(
                    run_id, ValidationInterface.StatusEnum.completed
                )

        if reasoning_content:
            logging_utility.info(
                f"Run {run_id}: Final reasoning content length: {len(reasoning_content)}"
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
            f"Processing conversation for run {run_id} with model {model}. "
            f"API key provided: {'Yes' if api_key else 'No'}"
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
