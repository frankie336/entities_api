from __future__ import annotations

import json
import os
import re
from typing import Any, Generator, Optional

from dotenv import load_dotenv
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from src.api.entities_api.dependencies import get_redis
from src.api.entities_api.inference_mixin.mixins import (
    AssistantCacheMixin,
    CodeExecutionMixin,
    ConsumerToolHandlersMixin,
    ConversationContextMixin,
    FileSearchMixin,
    JsonUtilsMixin,
    PlatformToolHandlersMixin,
    ShellExecutionMixin,
    ToolRoutingMixin,
)
from src.api.entities_api.inference_mixin.orchestrator_core import OrchestratorCore
from src.api.entities_api.inference_mixin.providers.hypherbolic.hyperbolic_async_client import (
    AsyncHyperbolicClient,
)
from src.api.entities_api.utils.async_to_sync import async_to_sync_stream

load_dotenv()
LOG = LoggingUtility()


class _ProviderMixins(
    AssistantCacheMixin,
    JsonUtilsMixin,
    ConversationContextMixin,
    ToolRoutingMixin,
    PlatformToolHandlersMixin,
    ConsumerToolHandlersMixin,
    CodeExecutionMixin,
    ShellExecutionMixin,
    FileSearchMixin,
):
    """Flat mix-in bundle so the concrete provider only inherits once."""


class HyperbolicR1Inference(_ProviderMixins, OrchestratorCore):

    def __init__(
        self,
        *,
        assistant_id: str | None = None,
        thread_id: str | None = None,
        redis=None,
        base_url: str | None = None,
        api_key: str | None = None,
        assistant_cache: dict | None = None,
        **extra,
    ):
        self._assistant_cache = assistant_cache or {}
        self.redis = redis or get_redis()
        self.assistant_id = assistant_id
        self.thread_id = thread_id
        self.base_url = base_url or os.getenv("HYPERBOLIC_BASE_URL")
        self.api_key = api_key
        self.model_name = extra.get("model_name", "deepseek-ai/DeepSeek-R1")
        self.max_context_window = extra.get("max_context_window", 128000)
        self.threshold_percentage = extra.get("threshold_percentage", 0.8)
        super().__init__(**extra)
        LOG.debug(
            "HyperbolicR1Inference ready (assistant=%s)", assistant_id or "<lazy>"
        )

    @property
    def assistant_cache(self) -> dict:
        return self._assistant_cache

    @assistant_cache.setter
    def assistant_cache(self, value: dict) -> None:
        if hasattr(self, "_assistant_cache") and self._assistant_cache:
            raise AttributeError("assistant_cache already meaningfully initialised")
        self._assistant_cache = value

    def get_assistant_cache(self) -> dict:
        return self._assistant_cache

    def _filter_fc(self, chunk_json: str) -> Optional[str]:
        try:
            loaded_chunk = json.loads(chunk_json)
            if (
                isinstance(loaded_chunk, dict)
                and loaded_chunk.get("type") == "function_call"
            ):
                return None
        except Exception:
            pass
        return chunk_json

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
        redis = self.redis
        stream_key = f"stream:{run_id}"
        self.start_cancellation_listener(run_id)
        if mapped := self._get_model_map(model):
            model = mapped
        ctx_messages = self._set_up_context_window(assistant_id, thread_id, trunk=True)
        current_api_key = api_key or self.api_key
        if not current_api_key:
            err_dict = {
                "type": "error",
                "content": "Missing API key for Hyperbolic R1.",
            }
            err_json = json.dumps(err_dict)
            yield err_json
            self._shunt_to_redis_stream(redis, stream_key, err_dict)
            return
        current_base_url = self.base_url
        if not current_base_url:
            err_dict = {
                "type": "error",
                "content": "Hyperbolic R1 service base URL not configured.",
            }
            err_json = json.dumps(err_dict)
            yield err_json
            self._shunt_to_redis_stream(redis, stream_key, err_dict)
            return
        try:
            client = AsyncHyperbolicClient(
                api_key=current_api_key, base_url=current_base_url
            )
        except Exception as exc:
            err_dict = {
                "type": "error",
                "content": f"Hyperbolic R1 client init failed: {exc}",
            }
            err_json = json.dumps(err_dict)
            yield err_json
            self._shunt_to_redis_stream(redis, stream_key, err_dict)
            return
        current_assistant_text_reply = ""
        raw_llm_stream_accumulator = ""
        current_reasoning_text = ""
        current_fc_json_buffer = ""
        in_reasoning_block = False
        in_function_call_block = False
        in_code_interpreter_mode = False
        code_interpreter_code_buffer = ""
        try:
            prompt_for_client = (
                json.dumps(ctx_messages)
                if isinstance(ctx_messages, list)
                else str(ctx_messages)
            )
            async_stream = client.stream_chat_completion(
                prompt=prompt_for_client, model=model, temperature=0.6
            )
            for token_str in async_to_sync_stream(async_stream):
                if self.check_cancellation_flag():
                    err_dict = {"type": "error", "content": "Run cancelled"}
                    err_json = json.dumps(err_dict)
                    yield err_json
                    self._shunt_to_redis_stream(redis, stream_key, err_dict)
                    break
                if not token_str:
                    continue
                for seg in filter(
                    None, re.split("(<think>|</think>|<fc>|</fc>)", token_str)
                ):
                    raw_llm_stream_accumulator += seg
                    if seg in ("<think>", "</think>", "<fc>", "</fc>"):
                        if seg == "<fc>":
                            in_function_call_block = True
                            current_fc_json_buffer = ""
                        elif seg == "</fc>":
                            in_function_call_block = False
                            stripped_fc_json = current_fc_json_buffer.strip()
                            try:
                                parsed_fc = json.loads(stripped_fc_json)
                                if self.is_valid_function_call_response(parsed_fc):
                                    self._shunt_to_redis_stream(
                                        redis,
                                        stream_key,
                                        {
                                            "type": "function_call",
                                            "content": stripped_fc_json,
                                        },
                                    )
                                else:
                                    LOG.warning(
                                        f"Run {run_id}: FC invalid by structure: {stripped_fc_json[:100]}"
                                    )
                            except Exception as e:
                                LOG.warning(
                                    f"Run {run_id}: Error parsing FC: {e}, Buffer: '{current_fc_json_buffer[:100]}'"
                                )
                            current_fc_json_buffer = ""
                        elif seg == "<think>":
                            in_reasoning_block = True
                        elif seg == "</think>":
                            in_reasoning_block = False
                        if stream_reasoning and seg in ("<think>", "</think>"):
                            msg_dict = {"type": "reasoning", "content": seg}
                            msg_json = json.dumps(msg_dict)
                            if p := self._filter_fc(msg_json):
                                yield p
                            self._shunt_to_redis_stream(redis, stream_key, msg_dict)
                        continue
                    if in_function_call_block:
                        current_fc_json_buffer += seg
                        continue
                    if in_reasoning_block:
                        current_reasoning_text += seg
                        if stream_reasoning:
                            msg_dict = {"type": "reasoning", "content": seg}
                            msg_json = json.dumps(msg_dict)
                            if p := self._filter_fc(msg_json):
                                yield p
                            self._shunt_to_redis_stream(redis, stream_key, msg_dict)
                        continue
                    current_assistant_text_reply += seg
                    parse_ci = getattr(self, "parse_code_interpreter_partial", None)
                    partial_match = (
                        parse_ci(raw_llm_stream_accumulator) if parse_ci else None
                    )
                    if not in_code_interpreter_mode and partial_match:
                        in_code_interpreter_mode = True
                        code_interpreter_code_buffer = partial_match.get("code", "")
                        start_msg_dict = {"type": "hot_code", "content": "```python\n"}
                        start_msg_json = json.dumps(start_msg_dict)
                        if p := self._filter_fc(start_msg_json):
                            yield p
                        self._shunt_to_redis_stream(redis, stream_key, start_msg_dict)
                        if code_interpreter_code_buffer and hasattr(
                            self, "_process_code_interpreter_chunks"
                        ):
                            results, code_interpreter_code_buffer = (
                                self._process_code_interpreter_chunks(
                                    "", code_interpreter_code_buffer
                                )
                            )
                            for r_json_str in results:
                                if p := self._filter_fc(r_json_str):
                                    yield p
                                self._shunt_to_redis_stream(
                                    redis, stream_key, json.loads(r_json_str)
                                )
                        continue
                    if in_code_interpreter_mode:
                        if hasattr(self, "_process_code_interpreter_chunks"):
                            results, code_interpreter_code_buffer = (
                                self._process_code_interpreter_chunks(
                                    seg, code_interpreter_code_buffer
                                )
                            )
                            for r_json_str in results:
                                if p := self._filter_fc(r_json_str):
                                    yield p
                                self._shunt_to_redis_stream(
                                    redis, stream_key, json.loads(r_json_str)
                                )
                                try:
                                    r_dict = json.loads(r_json_str)
                                    if r_dict.get("type") == "end_hot_code":
                                        in_code_interpreter_mode = False
                                except:
                                    pass
                        else:
                            fallback_msg_dict = {"type": "hot_code", "content": seg}
                            fallback_msg_json = json.dumps(fallback_msg_dict)
                            if p := self._filter_fc(fallback_msg_json):
                                yield p
                            self._shunt_to_redis_stream(
                                redis, stream_key, fallback_msg_dict
                            )
                        if not (
                            parse_ci(raw_llm_stream_accumulator) if parse_ci else False
                        ):
                            in_code_interpreter_mode = False
                        continue
                    msg_dict = {"type": "content", "content": seg}
                    msg_json = json.dumps(msg_dict)
                    if p := self._filter_fc(msg_json):
                        yield p
                    self._shunt_to_redis_stream(redis, stream_key, msg_dict)
        except Exception as exc:
            LOG.error(
                f"Run {run_id}: Hyperbolic R1 SDK error in stream: {exc}", exc_info=True
            )
            err_dict = {"type": "error", "content": f"Hyperbolic R1 SDK error: {exc}"}
            err_json = json.dumps(err_dict)
            yield err_json
            self._shunt_to_redis_stream(redis, stream_key, err_dict)
            return
        if current_assistant_text_reply or current_reasoning_text:
            self.finalize_conversation(
                current_reasoning_text + current_assistant_text_reply,
                thread_id,
                assistant_id,
                run_id,
            )
        if raw_llm_stream_accumulator and self.parse_and_set_function_calls(
            raw_llm_stream_accumulator, current_assistant_text_reply
        ):
            self.project_david_client.runs.update_run_status(
                run_id, StatusEnum.pending_action.value
            )
        elif not self.get_function_call_state():
            self.project_david_client.runs.update_run_status(
                run_id, StatusEnum.completed.value
            )
        if current_reasoning_text:
            LOG.info(
                "Run %s: Final R1 reasoning length %d",
                run_id,
                len(current_reasoning_text),
            )
        LOG.info("Run %s: R1 Stream processing finished.", run_id)

    def process_conversation(
        self,
        thread_id: str,
        message_id: str,
        run_id: str,
        assistant_id: str,
        model: Any,
        *,
        stream_reasoning: bool = False,
        api_key: Optional[str] = None,
    ) -> Generator[str, None, None]:
        yield from self.stream(
            thread_id,
            message_id,
            run_id,
            assistant_id,
            model,
            stream_reasoning=stream_reasoning,
            api_key=api_key,
        )
        fc_pending: bool = bool(self.get_function_call_state())
        if fc_pending:
            yield from self.process_function_calls(
                thread_id, run_id, assistant_id, model=model, api_key=api_key
            )
            yield from self.stream(
                thread_id,
                message_id,
                run_id,
                assistant_id,
                model,
                stream_reasoning=stream_reasoning,
                api_key=api_key,
            )
