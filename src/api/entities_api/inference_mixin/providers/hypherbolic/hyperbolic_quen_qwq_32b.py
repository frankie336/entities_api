from __future__ import annotations

"""
Hyperbolic-Quen-Qwq-32B provider
———————————————
• Async Hyperbolic SDK (AsyncHyperbolicClient) → streamed through
  async_to_sync_stream just like the original class.
• Supports optional <think> … </think> reasoning tags
  (define self.REASONING_PATTERN in a prompt helper if desired).
• Code-interpreter hot-code logic copied verbatim.
"""

import json
import os
from typing import Any, Generator, Optional

from dotenv import load_dotenv
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from entities_api.dependencies import get_redis
from entities_api.inference.hypherbolic.hyperbolic_async_client import \
    AsyncHyperbolicClient
from entities_api.inference_mixin.mixins import (AssistantCacheMixin,
                                                 CodeExecutionMixin,
                                                 ConsumerToolHandlersMixin,
                                                 ConversationContextMixin,
                                                 FileSearchMixin,
                                                 JsonUtilsMixin,
                                                 PlatformToolHandlersMixin,
                                                 ShellExecutionMixin,
                                                 ToolRoutingMixin)
from entities_api.inference_mixin.orchestrator_core import OrchestratorCore
from entities_api.utils.async_to_sync import async_to_sync_stream

load_dotenv()
LOG = LoggingUtility()


# --------------------------------------------------------------------------- #
# mix-in bundle (same as other providers)
# --------------------------------------------------------------------------- #
class _ProviderMixins(  # pylint: disable=too-many-ancestors
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


# --------------------------------------------------------------------------- #
# provider
# --------------------------------------------------------------------------- #
class HyperbolicQuenQwq32B(_ProviderMixins, OrchestratorCore):
    """Async Hyperbolic Quen-Qwq-32B streaming provider."""

    # ------------------------------------------------------------------ #
    # ctor
    # ------------------------------------------------------------------ #
    def __init__(  # noqa: D401
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
        self.max_context_window = extra.get("max_context_window", 128_000)
        self.threshold_percentage = extra.get("threshold_percentage", 0.8)

        self.setup_services()
        LOG.debug("Hyperbolic-Qwq-32B provider ready (assistant=%s)", assistant_id)

    # ------------------------------------------------------------------ #
    # ConversationContextMixin shim
    # ------------------------------------------------------------------ #
    @property
    def assistant_cache(self) -> dict:
        return self._assistant_cache

    @assistant_cache.setter
    def assistant_cache(self, value: dict) -> None:
        if hasattr(self, "_assistant_cache"):
            raise AttributeError("assistant_cache already initialised")
        self._assistant_cache = value

    def get_assistant_cache(self) -> dict:  # noqa: D401
        return self._assistant_cache

    # ------------------------------------------------------------------ #
    # small helper – strip provider-side function_call objects
    # ------------------------------------------------------------------ #
    @staticmethod
    def _filter_fc(chunk_json: str) -> Optional[str]:
        try:
            if json.loads(chunk_json).get("type") == "function_call":
                return None
        except Exception:
            pass
        return chunk_json

    # ------------------------------------------------------------------ #
    # streaming loop
    # ------------------------------------------------------------------ #
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

        if mapped := self._get_model_map(model):
            model = mapped

        messages = self._set_up_context_window(assistant_id, thread_id, trunk=True)
        prompt = messages[-1]["content"]

        # ----- prepare async Hyperbolic call ---------------------------
        if not api_key:
            err = {"type": "error", "content": "Missing API key for Hyperbolic."}
            yield json.dumps(err)
            self._shunt_to_redis_stream(redis, stream_key, err)
            return

        base_url = os.getenv("HYPERBOLIC_BASE_URL")
        if not base_url:
            err = {
                "type": "error",
                "content": "Hyperbolic service not configured (HYPERBOLIC_BASE_URL).",
            }
            yield json.dumps(err)
            self._shunt_to_redis_stream(redis, stream_key, err)
            return

        client = AsyncHyperbolicClient(api_key=api_key, base_url=base_url)
        async_stream = client.stream_chat_completion(
            prompt=prompt,
            model=model,
            temperature=0.6,
            top_p=0.9,
        )

        # ----- state ---------------------------------------------------
        assistant_reply = accumulated = reasoning_buf = ""
        in_reasoning = False
        code_mode = False
        code_buf = ""

        # Regex used if caller sets `self.REASONING_PATTERN`
        reasoning_re = getattr(self, "REASONING_PATTERN", None)
        splitter = (
            (lambda txt: reasoning_re.split(txt))
            if reasoning_re
            else (lambda txt: [txt])
        )

        # ① Emit a “started” status so front-end can immediately show Stop button
        start_chunk = {"type": "status", "status": "started", "run_id": run_id}
        yield json.dumps(start_chunk)
        self._shunt_to_redis_stream(redis, stream_key, start_chunk)

        try:
            for token in async_to_sync_stream(async_stream):
                if self.check_cancellation_flag():
                    err = {"type": "error", "content": "Run cancelled"}
                    if p := self._filter_fc(json.dumps(err)):
                        yield p
                    self._shunt_to_redis_stream(redis, stream_key, err)
                    break

                for seg in splitter(token):
                    if not seg:
                        continue

                    # --- reasoning tags ----------------------------------
                    if seg == "<think>":
                        in_reasoning = True
                        if stream_reasoning:
                            r = {"type": "reasoning", "content": seg}
                            if p := self._filter_fc(json.dumps(r)):
                                yield p
                            self._shunt_to_redis_stream(redis, stream_key, r)
                        continue
                    if seg == "</think>":
                        in_reasoning = False
                        if stream_reasoning:
                            r = {"type": "reasoning", "content": seg}
                            if p := self._filter_fc(json.dumps(r)):
                                yield p
                            self._shunt_to_redis_stream(redis, stream_key, r)
                        continue

                    # inside reasoning block
                    if in_reasoning:
                        reasoning_buf += seg
                        if stream_reasoning:
                            r = {"type": "reasoning", "content": seg}
                            if p := self._filter_fc(json.dumps(r)):
                                yield p
                            self._shunt_to_redis_stream(redis, stream_key, r)
                        continue

                    # --- normal / code-interpreter -----------------------
                    assistant_reply += seg
                    accumulated += seg

                    parse_ci = getattr(self, "parse_code_interpreter_partial", None)
                    ci_match = (
                        parse_ci(accumulated) if parse_ci and not code_mode else None
                    )
                    if ci_match:
                        code_mode = True
                        code_buf = ci_match.get("code", "")
                        start = {"type": "hot_code", "content": "```python\n"}
                        if p := self._filter_fc(json.dumps(start)):
                            yield p
                        self._shunt_to_redis_stream(redis, stream_key, start)

                        if code_buf and hasattr(
                            self, "_process_code_interpreter_chunks"
                        ):
                            res, code_buf = self._process_code_interpreter_chunks(
                                "", code_buf
                            )
                            for r in res:
                                if p := self._filter_fc(r):
                                    yield p
                                self._shunt_to_redis_stream(
                                    redis, stream_key, json.loads(r)
                                )
                        continue

                    if code_mode:
                        if hasattr(self, "_process_code_interpreter_chunks"):
                            res, code_buf = self._process_code_interpreter_chunks(
                                seg, code_buf
                            )
                            for r in res:
                                if p := self._filter_fc(r):
                                    yield p
                                self._shunt_to_redis_stream(
                                    redis, stream_key, json.loads(r)
                                )
                        else:
                            hot = {"type": "hot_code", "content": seg}
                            if p := self._filter_fc(json.dumps(hot)):
                                yield p
                            self._shunt_to_redis_stream(redis, stream_key, hot)
                        continue

                    # --- plain content -----------------------------------
                    msg = {"type": "content", "content": seg}
                    if p := self._filter_fc(json.dumps(msg)):
                        yield p
                    self._shunt_to_redis_stream(redis, stream_key, msg)

        except Exception as exc:  # noqa: BLE001
            err = {"type": "error", "content": f"Hyperbolic stream error: {exc}"}
            if p := self._filter_fc(json.dumps(err)):
                yield p
            self._shunt_to_redis_stream(redis, stream_key, err)
            return

        # ③ Emit a “complete” status so front-end can hide the Stop button
        end_chunk = {"type": "status", "status": "complete", "run_id": run_id}
        yield json.dumps(end_chunk)
        self._shunt_to_redis_stream(redis, stream_key, end_chunk)

        # ----- bookkeeping --------------------------------------------
        if assistant_reply:
            self.finalize_conversation(
                reasoning_buf + assistant_reply, thread_id, assistant_id, run_id
            )

        if accumulated and self.parse_and_set_function_calls(
            accumulated, assistant_reply
        ):
            self.project_david_client.runs.update_run_status(
                run_id, StatusEnum.pending_action.value
            )
        else:
            self.project_david_client.runs.update_run_status(
                run_id, StatusEnum.completed.value
            )

    # ------------------------------------------------------------------ #
    # orchestrator
    # ------------------------------------------------------------------ #
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

        if self.get_function_call_state():
            yield from self.process_function_calls(
                thread_id, run_id, assistant_id, model=model, api_key=api_key
            )
