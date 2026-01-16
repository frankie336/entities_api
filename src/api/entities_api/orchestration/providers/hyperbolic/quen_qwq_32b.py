# src/api/entities_api/orchestration/providers/hyperbolic/quen_qwq_32b.py
from __future__ import annotations

import json
import os
from typing import Any, Generator, Optional

from dotenv import load_dotenv
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from entities_api.orchestration.engine.orchestrator_core import \
    OrchestratorCore
from src.api.entities_api.dependencies import get_redis
from src.api.entities_api.inference.hypherbolic.hyperbolic_async_client import \
    AsyncHyperbolicClient
from src.api.entities_api.orchestration.mixins import (
    AssistantCacheMixin, CodeExecutionMixin, ConsumerToolHandlersMixin,
    ConversationContextMixin, FileSearchMixin, JsonUtilsMixin,
    PlatformToolHandlersMixin, ShellExecutionMixin, ToolRoutingMixin)
from src.api.entities_api.orchestration.streaming.hyperbolic import \
    HyperbolicDeltaNormalizer
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
    """C3-safe flat bundle."""


class HyperbolicQuenQwq32B(_ProviderMixins, OrchestratorCore):
    """
    Modular Async Hyperbolic Qwen-QwQ-32B provider.
    Aligned with the Specialized Worker architecture.
    """

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
    ) -> None:
        self._assistant_cache: dict = assistant_cache or {}
        self.redis = redis or get_redis()
        self.assistant_id = assistant_id
        self.thread_id = thread_id
        self.base_url = base_url or os.getenv("BASE_URL")
        self.api_key = api_key
        self.model_name = extra.get("model_name", "quen/Qwen1_5-32B-Chat")
        self.max_context_window = extra.get("max_context_window", 128000)
        self.threshold_percentage = extra.get("threshold_percentage", 0.8)
        self.setup_services()
        LOG.debug("Hyperbolic-Qwq-32B provider ready (assistant=%s)", assistant_id)

    @property
    def assistant_cache(self) -> dict:
        return self._assistant_cache

    @assistant_cache.setter
    def assistant_cache(self, value: dict) -> None:
        if hasattr(self, "_assistant_cache") and self._assistant_cache:
            raise AttributeError("assistant_cache already initialised")
        self._assistant_cache = value

    def get_assistant_cache(self) -> dict:
        return self._assistant_cache

    def stream(
        self,
        thread_id: str,
        message_id: Optional[str],
        run_id: str,
        assistant_id: str,
        model: Any,
        *,
        stream_reasoning: bool = True,
        api_key: Optional[str] = None,
    ) -> Generator[str, None, None]:
        redis = get_redis()
        stream_key = f"stream:{run_id}"

        # Aligned with updated OrchestratorCore cancellation logic
        stop_event = self.start_cancellation_monitor(run_id)

        if mapped := self._get_model_map(model):
            model = mapped

        # Context setup
        messages = self._set_up_context_window(assistant_id, thread_id, trunk=True)
        prompt = messages[-1]["content"]

        if not api_key:
            err = {"type": "error", "content": "Missing API key for Hyperbolic."}
            yield json.dumps(err)
            self._shunt_to_redis_stream(redis, stream_key, err)
            return

        base_url = os.getenv("HYPERBOLIC_BASE_URL")
        client = AsyncHyperbolicClient(api_key=api_key, base_url=base_url)
        async_stream = client.stream_chat_completion(
            prompt=prompt, model=model, temperature=0.6, top_p=0.9
        )

        start_chunk = {"type": "status", "status": "started", "run_id": run_id}
        yield json.dumps(start_chunk)
        self._shunt_to_redis_stream(redis, stream_key, start_chunk)

        assistant_reply = ""
        accumulated = ""
        reasoning_reply = ""
        code_mode = False
        code_buf = ""
        current_block = None

        try:
            token_iterator = async_to_sync_stream(async_stream)

            for chunk in HyperbolicDeltaNormalizer.iter_deltas(token_iterator, run_id):
                if stop_event.is_set():
                    err = {"type": "error", "content": "Run cancelled"}
                    yield json.dumps(err)
                    self._shunt_to_redis_stream(redis, stream_key, err)
                    break

                ctype = chunk["type"]
                ccontent = chunk["content"]

                # TAG INJECTION & STATE TRACKING
                if ctype == "content":
                    if current_block == "fc":
                        accumulated += "</fc>"
                    elif current_block == "think":
                        accumulated += "</think>"
                    current_block = None
                    assistant_reply += ccontent
                    accumulated += ccontent
                elif ctype == "call_arguments":
                    if current_block != "fc":
                        if current_block == "think":
                            accumulated += "</think>"
                        accumulated += "<fc>"
                        current_block = "fc"
                    accumulated += ccontent
                elif ctype == "reasoning":
                    if current_block != "think":
                        if current_block == "fc":
                            accumulated += "</fc>"
                        accumulated += "<think>"
                        current_block = "think"
                    reasoning_reply += ccontent
                    accumulated += ccontent

                # CODE INTERPRETER INTERLEAVING
                if ctype == "content":
                    parse_ci = getattr(self, "parse_code_interpreter_partial", None)
                    ci_match = (
                        parse_ci(accumulated) if parse_ci and (not code_mode) else None
                    )

                    if ci_match:
                        code_mode = True
                        code_buf = ci_match.get("code", "")
                        start = {"type": "hot_code", "content": "```python\n"}
                        yield json.dumps(start)
                        self._shunt_to_redis_stream(redis, stream_key, start)
                        if code_buf and hasattr(self, "_process_code_interpreter_chunks"):
                            res, code_buf = self._process_code_interpreter_chunks("", code_buf)
                            for r in res:
                                yield r
                                self._shunt_to_redis_stream(redis, stream_key, json.loads(r))
                        continue

                    if code_mode:
                        if hasattr(self, "_process_code_interpreter_chunks"):
                            res, code_buf = self._process_code_interpreter_chunks(ccontent,
                                                                                  code_buf)
                            for r in res:
                                yield r
                                self._shunt_to_redis_stream(redis, stream_key, json.loads(r))
                        else:
                            hot = {"type": "hot_code", "content": ccontent}
                            yield json.dumps(hot)
                            self._shunt_to_redis_stream(redis, stream_key, hot)
                        continue

                # Standard stream emission
                yield json.dumps(chunk)
                self._shunt_to_redis_stream(redis, stream_key, chunk)

        except Exception as exc:
            err = {"type": "error", "content": f"Hyperbolic stream error: {exc}"}
            yield json.dumps(err)
            self._shunt_to_redis_stream(redis, stream_key, err)
            return

        # FINAL CLOSE-OUT
        if current_block == "fc":
            accumulated += "</fc>"
        elif current_block == "think":
            accumulated += "</think>"

        end_chunk = {"type": "status", "status": "complete", "run_id": run_id}
        yield json.dumps(end_chunk)
        self._shunt_to_redis_stream(redis, stream_key, end_chunk)

        if assistant_reply:
            self.finalize_conversation(
                reasoning_reply + assistant_reply, thread_id, assistant_id, run_id
            )

        # TOOL ROUTING
        if accumulated and self.parse_and_set_function_calls(accumulated, assistant_reply):
            self.project_david_client.runs.update_run_status(run_id,
                                                             StatusEnum.pending_action.value)
        else:
            self.project_david_client.runs.update_run_status(run_id, StatusEnum.completed.value)

    def process_conversation(self, thread_id, message_id, run_id, assistant_id, model, **kwargs):
        # Correctly extracting the api_key for the subsequent process_function_calls
        api_key_val = kwargs.get("api_key")

        yield from self.stream(thread_id, message_id, run_id, assistant_id, model, **kwargs)

        if self.get_function_call_state():
            yield from self.process_function_calls(
                thread_id,
                run_id,
                assistant_id,
                model=model,
                api_key=api_key_val
            )
            self.set_tool_response_state(False)
            self.set_function_call_state(None)
            yield from self.stream(
                thread_id,
                None,
                run_id,
                assistant_id,
                model,
                api_key=api_key_val,
                **kwargs
            )
