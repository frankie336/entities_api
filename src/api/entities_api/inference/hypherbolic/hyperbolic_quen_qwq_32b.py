import json
import os
from abc import ABC
from typing import Any, Generator, Optional

from dotenv import load_dotenv
from projectdavid_common import ValidationInterface
from projectdavid_common.utilities.logging_service import LoggingUtility

from src.api.entities_api.dependencies import get_redis
from src.api.entities_api.inference.base_inference import BaseInference
from src.api.entities_api.inference.hypherbolic.hyperbolic_async_client import \
    AsyncHyperbolicClient
from src.api.entities_api.utils.async_to_sync import async_to_sync_stream

load_dotenv()
logging_utility = LoggingUtility()


class HyperbolicQuenQwq32bInference(BaseInference, ABC):

    def setup_services(self):
        logging_utility.debug(
            "HyperbolicDeepSeekV3Inference specific setup completed (if any)."
        )

    def _shunt_to_redis_stream(
        self, redis, stream_key, chunk_dict, *, maxlen=1000, ttl_seconds=3600
    ):
        return super()._shunt_to_redis_stream(
            redis, stream_key, chunk_dict, maxlen=maxlen, ttl_seconds=ttl_seconds
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
        redis = get_redis()
        stream_key = f"stream:{run_id}"
        self.start_cancellation_listener(run_id)
        if self._get_model_map(value=model):
            model = self._get_model_map(value=model)
        messages = self._set_up_context_window(assistant_id, thread_id, trunk=True)
        request_payload = {
            "model": model,
            "messages": messages,
            "max_tokens": None,
            "temperature": 0.6,
            "top_p": 0.9,
            "stream": True,
        }
        if not api_key:
            logging_utility.error(f"Run {run_id}: No API key provided.")
            chunk = {"type": "error", "content": "Missing API key for Hyperbolic."}
            yield json.dumps(chunk)
            self._shunt_to_redis_stream(redis, stream_key, chunk)
            return
        hyperbolic_base_url = os.getenv("HYPERBOLIC_BASE_URL")
        if not hyperbolic_base_url:
            logging_utility.error(f"Run {run_id}: Missing HYPERBOLIC_BASE_URL.")
            chunk = {
                "type": "error",
                "content": "Hyperbolic service not configured. Contact support.",
            }
            yield json.dumps(chunk)
            self._shunt_to_redis_stream(redis, stream_key, chunk)
            return
        client = AsyncHyperbolicClient(api_key=api_key, base_url=hyperbolic_base_url)
        assistant_reply = ""
        accumulated_content = ""
        reasoning_content = ""
        in_reasoning = False
        code_mode = False
        code_buffer = ""
        try:
            async_stream = client.stream_chat_completion(
                prompt=messages[-1]["content"],
                model=model,
                temperature=request_payload["temperature"],
                top_p=request_payload["top_p"],
                max_tokens=request_payload["max_tokens"],
            )
            for token in async_to_sync_stream(async_stream):
                if self.check_cancellation_flag():
                    logging_utility.warning(f"Run {run_id} cancelled mid-stream")
                    chunk = {"type": "error", "content": "Run cancelled"}
                    yield json.dumps(chunk)
                    self._shunt_to_redis_stream(redis, stream_key, chunk)
                    break
                segments = (
                    self.REASONING_PATTERN.split(token)
                    if hasattr(self, "REASONING_PATTERN")
                    else [token]
                )
                for seg in segments:
                    if not seg:
                        continue
                    if seg == "<think>":
                        in_reasoning = True
                        reasoning_content += seg
                        if stream_reasoning:
                            chunk = {"type": "reasoning", "content": seg}
                            yield json.dumps(chunk)
                            self._shunt_to_redis_stream(redis, stream_key, chunk)
                        continue
                    elif seg == "</think>":
                        in_reasoning = False
                        reasoning_content += seg
                        if stream_reasoning:
                            chunk = {"type": "reasoning", "content": seg}
                            yield json.dumps(chunk)
                            self._shunt_to_redis_stream(redis, stream_key, chunk)
                        continue
                    if in_reasoning:
                        reasoning_content += seg
                        if stream_reasoning:
                            chunk = {"type": "reasoning", "content": seg}
                            yield json.dumps(chunk)
                            self._shunt_to_redis_stream(redis, stream_key, chunk)
                    else:
                        assistant_reply += seg
                        accumulated_content += seg
                        partial_match = (
                            self.parse_code_interpreter_partial(accumulated_content)
                            if hasattr(self, "parse_code_interpreter_partial")
                            else None
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
                            chunk = {"type": "hot_code", "content": "```python\n"}
                            yield json.dumps(chunk)
                            self._shunt_to_redis_stream(redis, stream_key, chunk)
                            if code_buffer and hasattr(
                                self, "_process_code_interpreter_chunks"
                            ):
                                results, code_buffer = (
                                    self._process_code_interpreter_chunks(
                                        "", code_buffer
                                    )
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
                                    self._process_code_interpreter_chunks(
                                        seg, code_buffer
                                    )
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
                        if not code_buffer:
                            chunk = {"type": "content", "content": seg}
                            yield json.dumps(chunk)
                            self._shunt_to_redis_stream(redis, stream_key, chunk)
        except Exception as e:
            error_msg = f"Hyperbolic client stream error: {str(e)}"
            logging_utility.error(f"Run {run_id}: {error_msg}", exc_info=True)
            if hasattr(self, "handle_error"):
                self.handle_error(
                    reasoning_content + assistant_reply, thread_id, assistant_id, run_id
                )
            chunk = {"type": "error", "content": error_msg}
            yield json.dumps(chunk)
            self._shunt_to_redis_stream(redis, stream_key, chunk)
            return
        if assistant_reply and hasattr(self, "finalize_conversation"):
            self.finalize_conversation(
                reasoning_content + assistant_reply, thread_id, assistant_id, run_id
            )
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
        self, thread_id, run_id, assistant_id, model=None, api_key: Optional[str] = None
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
        if self._get_model_map(value=model):
            model = self._get_model_map(value=model)
        logging_utility.info(
            f"Processing conversation for run {run_id} with model {model}. API key provided: {('Yes' if api_key else 'No')}"
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
