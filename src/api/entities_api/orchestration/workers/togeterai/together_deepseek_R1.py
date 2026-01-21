"""
Together-AI DeepSeek-R1 provider (mixin edition)

Key points
----------
• Same streaming / tool-routing semantics as the legacy BaseInference version
• Suppresses {"type": "function_call", ...} chunks from the *client* while still
  forwarding them to Redis
• Two-pass orchestration: model->tools->model (only if tools were invoked)
• Optional per-request Together-AI API-key overrides
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Generator, Optional

from dotenv import load_dotenv
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from entities_api.orchestration.engine.orchestrator_core import \
    OrchestratorCore
from src.api.entities_api.dependencies import get_redis
from src.api.entities_api.orchestration.mixins import (
    AssistantCacheMixin, CodeExecutionMixin, ConsumerToolHandlersMixin,
    ConversationContextMixin, FileSearchMixin, JsonUtilsMixin,
    PlatformToolHandlersMixin, ShellExecutionMixin, ToolRoutingMixin)

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
    """Flattened mix-ins so the concrete provider inherits only once."""


class TogetherDeepSeekR1Inference(_ProviderMixins, OrchestratorCore):

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
        self.base_url = base_url or os.getenv("TOGETHER_BASE_URL")
        self.api_key = api_key
        self.model_name = extra.get("model_name", "deepseek-ai/DeepSeek-R1")
        self.max_context_window = extra.get("max_context_window", 128000)
        self.threshold_percentage = extra.get("threshold_percentage", 0.8)
        self.setup_services()
        LOG.debug("TogetherDeepSeekR1 ready (assistant=%s)", assistant_id or "<lazy>")

    @property
    def assistant_cache(self) -> dict:
        return self._assistant_cache

    @assistant_cache.setter
    def assistant_cache(self, value: dict) -> None:
        if hasattr(self, "_assistant_cache"):
            raise AttributeError("assistant_cache already initialised")
        self._assistant_cache = value

    def get_assistant_cache(self) -> dict:
        return self._assistant_cache

    def _filter_fc(self, chunk_json: str) -> Optional[str]:
        try:
            if json.loads(chunk_json).get("type") == "function_call":
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
        """
        Together-AI DeepSeek-R1 streaming.

        • Function-call JSON never hits the client.
        • Reasoning / hot-code behaviour mirrors other mix-in workers.
        """
        redis = self.redis
        stream_key = f"stream:{run_id}"
        self.start_cancellation_listener(run_id)
        if mapped := self._get_model_map(model):
            model = mapped
        req_payload = {
            "model": model,
            "messages": self._set_up_context_window(
                assistant_id, thread_id, trunk=True
            ),
            "max_tokens": None,
            "temperature": 0.6,
            "stream": True,
        }
        try:
            client = self._get_together_client(api_key=api_key or self.api_key)
        except Exception as exc:
            err = {"type": "error", "content": f"TogetherAI client init failed: {exc}"}
            if p := self._filter_fc(json.dumps(err)):
                yield p
            self._shunt_to_redis_stream(redis, stream_key, err)
            return
        start_chunk = {"type": "status", "status": "started", "run_id": run_id}
        yield json.dumps(start_chunk)
        self._shunt_to_redis_stream(redis, stream_key, start_chunk)
        assistant_reply = ""
        accumulated_content = ""
        reasoning_content = ""
        fc_buffer = ""
        in_reasoning = False
        in_function_call = False
        code_mode = False
        code_buffer = ""
        try:
            for token in client.chat.completions.create(**req_payload):
                if self.check_cancellation_flag():
                    err = {"type": "error", "content": "Run cancelled"}
                    if p := self._filter_fc(json.dumps(err)):
                        yield p
                    self._shunt_to_redis_stream(redis, stream_key, err)
                    break
                if not token.choices or not token.choices[0].delta:
                    continue
                delta = token.choices[0].delta
                delta_reason = getattr(delta, "reasoning_content", "")
                if delta_reason and stream_reasoning:
                    msg = {"type": "reasoning", "content": delta_reason}
                    if p := self._filter_fc(json.dumps(msg)):
                        yield p
                    self._shunt_to_redis_stream(redis, stream_key, msg)
                delta_content = getattr(delta, "content", "")
                if not delta_content:
                    continue
                for seg in filter(
                    None, re.split("(<think>|</think>|<fc>|</fc>)", delta_content)
                ):
                    if seg in ("<think>", "</think>", "<fc>", "</fc>"):
                        if seg == "<fc>":
                            in_function_call = True
                            fc_buffer = ""
                        elif seg == "</fc>":
                            in_function_call = False
                            try:
                                parsed_fc = json.loads(fc_buffer.strip())
                                if self.is_valid_function_call_response(parsed_fc):
                                    assistant_reply += fc_buffer
                                    accumulated_content += fc_buffer
                                    self._shunt_to_redis_stream(
                                        redis,
                                        stream_key,
                                        {"type": "function_call", "content": fc_buffer},
                                    )
                            except Exception:
                                LOG.warning("Invalid function_call payload ignored")
                            fc_buffer = ""
                        elif seg == "<think>":
                            in_reasoning = True
                        elif seg == "</think>":
                            in_reasoning = False
                        if stream_reasoning and seg in ("<think>", "</think>"):
                            msg = {"type": "reasoning", "content": seg}
                            if p := self._filter_fc(json.dumps(msg)):
                                yield p
                            self._shunt_to_redis_stream(redis, stream_key, msg)
                        continue
                    if in_function_call:
                        fc_buffer += seg
                        continue
                    if in_reasoning:
                        reasoning_content += seg
                        if stream_reasoning:
                            msg = {"type": "reasoning", "content": seg}
                            if p := self._filter_fc(json.dumps(msg)):
                                yield p
                            self._shunt_to_redis_stream(redis, stream_key, msg)
                        continue
                    assistant_reply += seg
                    accumulated_content += seg
                    parse_ci = getattr(self, "parse_code_interpreter_partial", None)
                    ci_match = parse_ci(accumulated_content) if parse_ci else None
                    if not code_mode and ci_match:
                        code_mode = True
                        code_buffer = ci_match.get("code", "")
                        start_msg = {"type": "hot_code", "content": "```python\n"}
                        if p := self._filter_fc(json.dumps(start_msg)):
                            yield p
                        self._shunt_to_redis_stream(redis, stream_key, start_msg)
                        if code_buffer and hasattr(
                            self, "_process_code_interpreter_chunks"
                        ):
                            results, code_buffer = (
                                self._process_code_interpreter_chunks("", code_buffer)
                            )
                            for r in results:
                                if p := self._filter_fc(r):
                                    yield p
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
                                if p := self._filter_fc(r):
                                    yield p
                                self._shunt_to_redis_stream(
                                    redis, stream_key, json.loads(r)
                                )
                        else:
                            msg = {"type": "hot_code", "content": seg}
                            if p := self._filter_fc(json.dumps(msg)):
                                yield p
                            self._shunt_to_redis_stream(redis, stream_key, msg)
                        continue
                    msg = {"type": "content", "content": seg}
                    if p := self._filter_fc(json.dumps(msg)):
                        yield p
                    self._shunt_to_redis_stream(redis, stream_key, msg)
        except Exception as exc:
            err = {"type": "error", "content": f"TogetherAI SDK error: {exc}"}
            if p := self._filter_fc(json.dumps(err)):
                yield p
            self._shunt_to_redis_stream(redis, stream_key, err)
            return
        end_chunk = {"type": "status", "status": "complete", "run_id": run_id}
        yield json.dumps(end_chunk)
        self._shunt_to_redis_stream(redis, stream_key, end_chunk)
        if assistant_reply:
            self.finalize_conversation(
                reasoning_content + assistant_reply, thread_id, assistant_id, run_id
            )
        if accumulated_content and self.parse_and_set_function_calls(
            accumulated_content, assistant_reply
        ):
            self.project_david_client.runs.update_run_status(
                run_id, StatusEnum.pending_action.value
            )
        elif not self.get_function_call_state():
            self.project_david_client.runs.update_run_status(
                run_id, StatusEnum.completed.value
            )
        if reasoning_content:
            LOG.info(
                "Run %s: Final reasoning length %d", run_id, len(reasoning_content)
            )

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
        """two-pass contract: model → tools → model (if tools executed)."""
        yield from self.stream(
            thread_id,
            message_id,
            run_id,
            assistant_id,
            model,
            stream_reasoning=stream_reasoning,
            api_key=api_key,
        )
        fc_pending = bool(self.get_function_call_state())
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
