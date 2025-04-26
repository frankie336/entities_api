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

    # --- helper -------------------------------------------------------
    # ------------------------------------------------------------
    # 🚦 universal filter: swallow any outgoing {"type":"function_call", ...}
    def _filter_fc(self, chunk_json: str) -> Optional[str]:
        """
        Hide function-call chunks from the *client* while still letting them
        reach Redis / downstream tool logic.

        Returns:
            str  -> pass through to client
            None -> suppress (do not yield)
        """
        try:
            if json.loads(chunk_json).get("type") == "function_call":
                return None
        except Exception:
            # if it isn't valid JSON, let it through
            pass
        return chunk_json

    # ------------------------------------------------------------
    def stream(
        self,
        thread_id: str,
        message_id: str,
        run_id: str,
        assistant_id: str,
        model: Any,
        *,
        stream_reasoning: bool = True,
        api_key: Optional[str] = None,
    ) -> Generator[str, None, None]:
        """
        HyperbolicDeepSeekV3Inference.stream

        • Any `function_call` chunks are written to Redis but **never** yielded
          to the client (suppressed via `_filter_fc`).
        • All other behaviour remains unchanged.
        """
        import re

        redis = get_redis()
        stream_key = f"stream:{run_id}"
        self.start_cancellation_listener(run_id)

        # -------- model mapping ---------------------------------------------
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

        # -------- Hyperbolic client -----------------------------------------
        client_to_use = None
        if api_key:
            try:
                client_to_use = self._get_openai_client(
                    base_url=os.getenv("HYPERBOLIC_BASE_URL"), api_key=api_key
                )
            except Exception as e:
                err = f"Hyperbolic client init failed: {e}"
                payload = json.dumps({"type": "error", "content": err})
                if filt := self._filter_fc(payload):
                    yield filt
                self._shunt_to_redis_stream(
                    redis, stream_key, {"type": "error", "content": err}
                )
                return

        if not client_to_use:
            err = "No Hyperbolic client available."
            payload = json.dumps({"type": "error", "content": err})
            if filt := self._filter_fc(payload):
                yield filt
            self._shunt_to_redis_stream(
                redis, stream_key, {"type": "error", "content": err}
            )
            return

        # -------- streaming loop --------------------------------------------
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
                    payload = json.dumps({"type": "error", "content": "Run cancelled"})
                    if filt := self._filter_fc(payload):
                        yield filt
                    self._shunt_to_redis_stream(
                        redis, stream_key, {"type": "error", "content": "Run cancelled"}
                    )
                    break

                if not getattr(token, "choices", None):
                    continue
                delta = token.choices[0].delta

                # ---------- reasoning ----------------------------------------
                delta_reasoning = getattr(delta, "reasoning_content", "")
                if delta_reasoning and stream_reasoning:
                    payload = json.dumps(
                        {"type": "reasoning", "content": delta_reasoning}
                    )
                    if filt := self._filter_fc(payload):
                        yield filt
                    self._shunt_to_redis_stream(
                        redis,
                        stream_key,
                        {"type": "reasoning", "content": delta_reasoning},
                    )

                delta_content = getattr(delta, "content", "")
                if not delta_content:
                    continue

                # ---------- tag-aware split ----------------------------------
                for seg in filter(
                    None, re.split(r"(<think>|</think>|<fc>|</fc>)", delta_content)
                ):

                    # tag state machine
                    if seg in ("<think>", "</think>", "<fc>", "</fc>"):
                        in_reasoning = (
                            seg == "<think>" or in_reasoning and seg != "</think>"
                        )
                        in_function_call = (
                            seg == "<fc>" or in_function_call and seg != "</fc>"
                        )
                        if stream_reasoning and seg in ("<think>", "</think>"):
                            payload = json.dumps({"type": "reasoning", "content": seg})
                            if filt := self._filter_fc(payload):
                                yield filt
                            self._shunt_to_redis_stream(
                                redis, stream_key, {"type": "reasoning", "content": seg}
                            )
                        continue

                    # ---------- function-call blocks --------------------------
                    is_fc_json = in_function_call
                    if not is_fc_json:
                        try:
                            is_fc_json = self.is_valid_function_call_response(
                                json.loads(seg.strip())
                            )
                        except Exception:
                            is_fc_json = False

                    if is_fc_json:
                        assistant_reply += seg
                        accumulated_content += seg
                        # push to Redis
                        self._shunt_to_redis_stream(
                            redis, stream_key, {"type": "function_call", "content": seg}
                        )
                        # never yield – filter absorbs
                        continue

                    # ---------- inside <think> -------------------------------
                    if in_reasoning:
                        reasoning_content += seg
                        if stream_reasoning:
                            payload = json.dumps({"type": "reasoning", "content": seg})
                            if filt := self._filter_fc(payload):
                                yield filt
                            self._shunt_to_redis_stream(
                                redis, stream_key, {"type": "reasoning", "content": seg}
                            )
                        continue

                    # ---------- code-interpreter or plain content ------------
                    assistant_reply += seg
                    accumulated_content += seg

                    # hot-code opening detection
                    parse_ci = getattr(self, "parse_code_interpreter_partial", None)
                    partial_match = parse_ci(accumulated_content) if parse_ci else None

                    if not code_mode and partial_match:
                        code_mode = True
                        code_buffer = partial_match.get("code", "")
                        payload = json.dumps(
                            {"type": "hot_code", "content": "```python\n"}
                        )
                        if filt := self._filter_fc(payload):
                            yield filt
                        self._shunt_to_redis_stream(
                            redis,
                            stream_key,
                            {"type": "hot_code", "content": "```python\n"},
                        )
                        # prime interpreter if needed
                        if code_buffer and hasattr(
                            self, "_process_code_interpreter_chunks"
                        ):
                            results, code_buffer = (
                                self._process_code_interpreter_chunks("", code_buffer)
                            )
                            for r in results:
                                if filt := self._filter_fc(r):
                                    yield filt
                                self._shunt_to_redis_stream(
                                    redis, stream_key, json.loads(r)
                                )
                        continue

                    if code_mode:
                        if hasattr(self, "_process_code_interpreter_chunks"):
                            results, code_buffer = (
                                self._process_code_interpreter_chunks(seg, code_buffer)
                            )
                            for r in results:
                                if filt := self._filter_fc(r):
                                    yield filt
                                self._shunt_to_redis_stream(
                                    redis, stream_key, json.loads(r)
                                )
                        else:
                            payload = json.dumps({"type": "hot_code", "content": seg})
                            if filt := self._filter_fc(payload):
                                yield filt
                            self._shunt_to_redis_stream(
                                redis, stream_key, {"type": "hot_code", "content": seg}
                            )
                        continue

                    # ---------- plain content --------------------------------
                    payload = json.dumps({"type": "content", "content": seg})
                    if filt := self._filter_fc(payload):
                        yield filt
                    self._shunt_to_redis_stream(
                        redis, stream_key, {"type": "content", "content": seg}
                    )

        except Exception as e:
            err = f"Hyperbolic SDK error: {e}"
            payload = json.dumps({"type": "error", "content": err})
            if filt := self._filter_fc(payload):
                yield filt
            self._shunt_to_redis_stream(
                redis, stream_key, {"type": "error", "content": err}
            )
            return

        # ---------- final bookkeeping ---------------------------------------
        if assistant_reply and hasattr(self, "finalize_conversation"):
            self.finalize_conversation(
                reasoning_content + assistant_reply, thread_id, assistant_id, run_id
            )

        if accumulated_content and hasattr(self, "parse_and_set_function_calls"):
            if self.parse_and_set_function_calls(accumulated_content, assistant_reply):
                self.run_service.update_run_status(
                    run_id, ValidationInterface.StatusEnum.pending_action
                )
            elif not self.get_function_call_state():
                self.run_service.update_run_status(
                    run_id, ValidationInterface.StatusEnum.completed
                )

        if reasoning_content:
            logging_utility.info(
                f"Run {run_id}: Final reasoning length {len(reasoning_content)}"
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
