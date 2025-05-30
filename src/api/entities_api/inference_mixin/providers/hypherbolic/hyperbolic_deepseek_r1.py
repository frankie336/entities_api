from __future__ import annotations

import json
import os
import re
from typing import Any, Generator, Optional

from dotenv import load_dotenv
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from entities_api.dependencies import get_redis
from entities_api.inference_mixin.mixins import (
    AssistantCacheMixin,
    JsonUtilsMixin,
    ConversationContextMixin,
    ToolRoutingMixin,
    PlatformToolHandlersMixin,
    ConsumerToolHandlersMixin,
    CodeExecutionMixin,
    ShellExecutionMixin,
    FileSearchMixin,
)
from entities_api.inference_mixin.orchestrator_core import OrchestratorCore
from entities_api.inference_mixin.providers.hypherbolic.hyperbolic_async_client import (
    AsyncHyperbolicClient,
)
from entities_api.utils.async_to_sync import async_to_sync_stream

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
    """
    Concrete provider refactored into mixin-based architecture.
    Streams reasoning, content, and hot-code deltas via AsyncHyperbolicClient,
    suppresses function_call chunks, and logs every reasoning segment.
    """

    # pattern to split on <think> and </think>
    REASONING_PATTERN = re.compile(r"(<think>|</think>)")

    def __init__(
        self,
        *,
        assistant_id: str | None = None,
        thread_id: str | None = None,
        redis: Any = None,
        base_url: str | None = None,
        api_key: str | None = None,
        assistant_cache: dict | None = None,
        **extra,
    ):
        self._assistant_cache = assistant_cache or {}
        if redis is None:
            raise ValueError("Redis client must be provided to HyperbolicR1Inference")
        self.redis = redis
        self.assistant_id = assistant_id
        self.thread_id = thread_id
        self.base_url = base_url or os.getenv("HYPERBOLIC_BASE_URL")
        self.api_key = api_key

        self.model_name = extra.get(
            "model_name", extra.get("model", "deepseek-ai/DeepSeek-R1")
        )
        self.max_context_window = extra.get("max_context_window", 128_000)
        self.threshold_percentage = extra.get("threshold_percentage", 0.8)

        self.setup_services()
        LOG.debug("HyperbolicR1Inference ready (assistant=%s)", assistant_id or "<lazy>")

    @property
    def assistant_cache(self) -> dict:
        return self._assistant_cache

    @assistant_cache.setter
    def assistant_cache(self, value: dict) -> None:
        if hasattr(self, "_assistant_cache"):
            raise AttributeError("assistant_cache already initialised")
        self._assistant_cache = value

    def setup_services(self):
        LOG.debug("HyperbolicR1Inference specific setup completed (if any).")

    def _filter_fc(self, chunk_json: str) -> Optional[str]:
        # never yield function_call chunks to client
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
        redis = get_redis()
        stream_key = f"stream:{run_id}"
        self.start_cancellation_listener(run_id)

        # remap alias → model
        if mapped := self._get_model_map(model):
            model = mapped

        messages = self._set_up_context_window(assistant_id, thread_id, trunk=True)

        # require API key
        if not (key := (api_key or self.api_key)):
            chunk = {"type": "error", "content": "Missing API key for Hyperbolic."}
            yield json.dumps(chunk)
            self._shunt_to_redis_stream(redis, stream_key, chunk)
            return

        # require base URL
        if not (base := (self.base_url or os.getenv("HYPERBOLIC_BASE_URL"))):
            chunk = {
                "type": "error",
                "content": "Hyperbolic service not configured. Contact support.",
            }
            yield json.dumps(chunk)
            self._shunt_to_redis_stream(redis, stream_key, chunk)
            return

        client = AsyncHyperbolicClient(api_key=key, base_url=base)
        assistant_reply = ""
        accumulated = ""
        reasoning_buf = ""
        in_reasoning = False
        code_mode = False
        code_buf = ""

        try:
            async_stream = client.stream_chat_completion(
                prompt=messages[-1]["content"],
                model=model,
                temperature=0.6,
                top_p=0.9,
                max_tokens=None,
            )

            for token in async_to_sync_stream(async_stream):
                # cancellation?
                if self.check_cancellation_flag():
                    chunk = {"type": "error", "content": "Run cancelled"}
                    yield json.dumps(chunk)
                    self._shunt_to_redis_stream(redis, stream_key, chunk)
                    break

                # split on <think> tags
                segments = self.REASONING_PATTERN.split(token)
                for seg in segments:
                    if not seg:
                        continue

                    # start reasoning
                    if seg == "<think>":
                        in_reasoning = True
                        LOG.debug(">> entering reasoning block")
                        reasoning_buf += seg
                        if stream_reasoning:
                            chunk = {"type": "reasoning", "content": seg}
                            yield json.dumps(chunk)
                            self._shunt_to_redis_stream(redis, stream_key, chunk)
                        continue

                    # end reasoning
                    if seg == "</think>":
                        in_reasoning = False
                        LOG.debug("<< exiting reasoning block")
                        reasoning_buf += seg
                        if stream_reasoning:
                            chunk = {"type": "reasoning", "content": seg}
                            yield json.dumps(chunk)
                            self._shunt_to_redis_stream(redis, stream_key, chunk)
                        continue

                    # inside reasoning
                    if in_reasoning:
                        LOG.debug("reasoning chunk: %r", seg)
                        reasoning_buf += seg
                        if stream_reasoning:
                            chunk = {"type": "reasoning", "content": seg}
                            yield json.dumps(chunk)
                            self._shunt_to_redis_stream(redis, stream_key, chunk)
                        continue

                    # outside reasoning → content or hot_code
                    assistant_reply += seg
                    accumulated += seg

                    # detect code-interpreter start
                    parse_ci = getattr(self, "parse_code_interpreter_partial", None)
                    partial = parse_ci(accumulated) if parse_ci else None

                    if not code_mode and partial:
                        full = partial.get("full_match", "")
                        if full:
                            idx = accumulated.find(full)
                            if idx != -1:
                                accumulated = accumulated[idx + len(full) :]
                        code_mode = True
                        code_buf = partial.get("code", "")
                        LOG.debug("~~ hot_code start")
                        chunk = {"type": "hot_code", "content": "```python\n"}
                        yield json.dumps(chunk)
                        self._shunt_to_redis_stream(redis, stream_key, chunk)

                        # any buffered code
                        if code_buf and hasattr(self, "_process_code_interpreter_chunks"):
                            results, code_buf = self._process_code_interpreter_chunks("", code_buf)
                            for r in results:
                                yield r
                                self._shunt_to_redis_stream(redis, stream_key, r)
                        continue

                    # streaming code segments
                    if code_mode:
                        if hasattr(self, "_process_code_interpreter_chunks"):
                            results, code_buf = self._process_code_interpreter_chunks(seg, code_buf)
                            for r in results:
                                yield r
                                self._shunt_to_redis_stream(redis, stream_key, r)
                        else:
                            chunk = {"type": "hot_code", "content": seg}
                            yield json.dumps(chunk)
                            self._shunt_to_redis_stream(redis, stream_key, chunk)
                        continue

                    # plain content
                    chunk = {"type": "content", "content": seg}
                    yield json.dumps(chunk)
                    self._shunt_to_redis_stream(redis, stream_key, chunk)

        except Exception as exc:
            error_msg = f"Hyperbolic client stream error: {exc}"
            LOG.error(f"Run {run_id}: {error_msg}", exc_info=True)
            if hasattr(self, "handle_error"):
                self.handle_error(reasoning_buf + assistant_reply, thread_id, assistant_id, run_id)
            chunk = {"type": "error", "content": error_msg}
            yield json.dumps(chunk)
            self._shunt_to_redis_stream(redis, stream_key, chunk)
            return

        # final wrap-up
        if assistant_reply:
            self.finalize_conversation(reasoning_buf + assistant_reply, thread_id, assistant_id, run_id)

        # function-call post-processing
        if accumulated and self.parse_and_set_function_calls(accumulated, assistant_reply):
            self.run_service.update_run_status(run_id, StatusEnum.pending_action)
        elif not self.get_function_call_state():
            self.run_service.update_run_status(run_id, StatusEnum.completed)

        if reasoning_buf:
            LOG.info("Run %s: Final reasoning content length %d", run_id, len(reasoning_buf))

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
        # ① initial stream
        yield from self.stream(
            thread_id=thread_id,
            message_id=message_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            stream_reasoning=stream_reasoning,
            api_key=api_key,
        )
        # ② run any tools
        if self.get_function_call_state():
            yield from self.process_function_calls(
                thread_id=thread_id,
                run_id=run_id,
                assistant_id=assistant_id,
                model=model,
                api_key=api_key,
            )
            # ③ follow-up stream
            yield from self.stream(
                thread_id=thread_id,
                message_id=message_id,
                run_id=run_id,
                assistant_id=assistant_id,
                model=model,
                stream_reasoning=stream_reasoning,
                api_key=api_key,
            )
