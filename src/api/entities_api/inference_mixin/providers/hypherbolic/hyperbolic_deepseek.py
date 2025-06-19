from __future__ import annotations

"""
Hyperbolic Ds1 – DeepSeek provider (raw-stream variant)
───────────────────────────────────────────────────────
• Streams deltas straight from the provider with **no** pre-cleaning:
    – we do **not** normalise <fc>/<think> tags or strip “[content]”.
    – no special buffering for <fc> … </fc> or <think> … </think>.
• Hot-code (<code-interpreter>) detection, Redis fan-out, status
  signalling, and function-call suppression remain unchanged.
"""

import json
import os
from typing import Any, Generator, Optional

from dotenv import load_dotenv
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from entities_api.dependencies import get_redis
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

load_dotenv()
LOG = LoggingUtility()


# --------------------------------------------------------------------------- #
# mix-in bundle (identical to Llama-3 & previous Ds1)
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
    """Flat bundle → single inheritance in the concrete class."""


# --------------------------------------------------------------------------- #
# provider
# --------------------------------------------------------------------------- #
class HyperbolicDs1(_ProviderMixins, OrchestratorCore):
    """
    DeepSeek-V3 served by Hyperbolic – streaming & tool orchestration.
    """

    # ------------------------------------------------------------------ #
    # construction
    # ------------------------------------------------------------------ #
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

        # model defaults
        self.model_name = extra.get("model_name", "deepseek-ai/DeepSeek-V3")
        self.max_context_window = extra.get("max_context_window", 128_000)
        self.threshold_percentage = extra.get("threshold_percentage", 0.8)

        self.setup_services()
        LOG.debug("Hyperbolic-Ds1 provider ready (assistant=%s)", assistant_id)

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
        stop_event = self.start_cancellation_monitor(run_id)

        if mapped := self._get_model_map(model):
            model = mapped
        ctx = self._set_up_context_window(assistant_id, thread_id, trunk=True)

        if model == "deepseek-ai/DeepSeek-R1":
            amended = self._build_amended_system_message(assistant_id=assistant_id)
            ctx = self.replace_system_message(
                ctx, json.dumps(amended, ensure_ascii=False, indent=2)
            )

        payload = {
            "model": model,
            "messages": ctx,
            "max_tokens": 10000,
            "temperature": 0.6,
            "stream": True,
        }

        # Emit "started" so UI shows Stop button
        start_chunk = {"type": "status", "status": "started", "run_id": run_id}
        yield json.dumps(start_chunk)
        self._shunt_to_redis_stream(redis, stream_key, start_chunk)

        try:
            client = self._get_openai_client(
                base_url=os.getenv("HYPERBOLIC_BASE_URL"), api_key=api_key
            )
        except Exception as exc:
            err = {"type": "error", "content": f"client init failed: {exc}"}
            yield json.dumps(err)
            self._shunt_to_redis_stream(redis, stream_key, err)
            return

        assistant_reply = accumulated = ""
        code_mode = False
        code_buf = ""

        try:
            for token in client.chat.completions.create(**payload):
                if stop_event.is_set():
                    err = {"type": "error", "content": "Run cancelled"}
                    yield json.dumps(err)
                    self._shunt_to_redis_stream(redis, stream_key, err)
                    break

                if not token.choices or not token.choices[0].delta:
                    continue

                seg = getattr(token.choices[0].delta, "content", "")
                if not seg:
                    continue

                assistant_reply += seg
                accumulated += seg

                parse_ci = getattr(self, "parse_code_interpreter_partial", None)
                ci_match = parse_ci(accumulated) if parse_ci and not code_mode else None

                if ci_match:
                    code_mode = True
                    code_buf = ci_match.get("code", "")
                    start = {"type": "hot_code", "content": "```python\n"}
                    yield json.dumps(start)
                    self._shunt_to_redis_stream(redis, stream_key, start)

                    if code_buf and hasattr(self, "_process_code_interpreter_chunks"):
                        res, code_buf = self._process_code_interpreter_chunks(
                            "", code_buf
                        )
                        for r in res:
                            yield r
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
                            yield r
                            self._shunt_to_redis_stream(
                                redis, stream_key, json.loads(r)
                            )
                    else:
                        hot = {"type": "hot_code", "content": seg}
                        yield json.dumps(hot)
                        self._shunt_to_redis_stream(redis, stream_key, hot)
                    continue

                msg = {"type": "content", "content": seg}
                yield json.dumps(msg)
                self._shunt_to_redis_stream(redis, stream_key, msg)

        except Exception as exc:
            err = {"type": "error", "content": f"Hyperbolic SDK error: {exc}"}
            yield json.dumps(err)
            self._shunt_to_redis_stream(redis, stream_key, err)
            return

        end_chunk = {"type": "status", "status": "complete", "run_id": run_id}
        yield json.dumps(end_chunk)
        self._shunt_to_redis_stream(redis, stream_key, end_chunk)

        if assistant_reply:
            self.finalize_conversation(assistant_reply, thread_id, assistant_id, run_id)

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
    # orchestrator (single pass + tools)
    # ------------------------------------------------------------------ #
    def process_conversation(  # noqa: D401
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
        # main model pass
        yield from self.stream(
            thread_id,
            message_id,
            run_id,
            assistant_id,
            model,
            stream_reasoning=stream_reasoning,
            api_key=api_key,
        )

        # tool pass (if a function_call was queued)
        if self.get_function_call_state():
            yield from self.process_function_calls(
                thread_id, run_id, assistant_id, model=model, api_key=api_key
            )
