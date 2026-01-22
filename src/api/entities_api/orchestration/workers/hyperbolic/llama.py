from __future__ import annotations

import json
import os
from typing import Any, Generator, Optional

from dotenv import load_dotenv
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from entities_api.utils.async_to_sync import async_to_sync_stream
from src.api.entities_api.dependencies import get_redis
from src.api.entities_api.orchestration.engine.orchestrator_core import \
    OrchestratorCore
from src.api.entities_api.orchestration.mixins import (
    AssistantCacheMixin, CodeExecutionMixin, ConsumerToolHandlersMixin,
    ConversationContextMixin, FileSearchMixin, JsonUtilsMixin,
    PlatformToolHandlersMixin, ShellExecutionMixin, ToolRoutingMixin)
from src.api.entities_api.orchestration.streaming.hyperbolic import \
    HyperbolicDeltaNormalizer

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
    """Flat bundle → single inheritance in the concrete class."""


class HyperbolicLlama33(_ProviderMixins, OrchestratorCore):
    """
    Modular Meta-Llama-3-33B Provider.
    Refactored to support Smart History Preservation and ensure Stage 2 compatibility.
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
        self._assistant_cache: dict = (
            assistant_cache or extra.get("assistant_cache") or {}
        )
        self.redis = redis or get_redis()
        self.assistant_id = assistant_id
        self.thread_id = thread_id
        self.base_url = base_url or os.getenv("BASE_URL")
        self.api_key = api_key

        # Attributes required by Truncator logic
        self.model_name = extra.get("model_name", "meta-llama/Llama-3.3-70B-Instruct")
        self.max_context_window = extra.get("max_context_window", 128000)
        self.threshold_percentage = extra.get("threshold_percentage", 0.8)

        self.setup_services()
        LOG.debug("Hyperbolic-Llama provider ready (assistant=%s)", assistant_id)

    @property
    def assistant_cache(self) -> dict:
        return self._assistant_cache

    @assistant_cache.setter
    def assistant_cache(self, value: dict) -> None:
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
        api_key: Optional[str] = None,
        **kwargs,
    ) -> Generator[str, None, None]:
        redis = get_redis()
        stream_key = f"stream:{run_id}"
        stop_event = self.start_cancellation_monitor(run_id)

        try:
            # 1. Clean Model ID
            if isinstance(model, str) and model.startswith("hyperbolic/"):
                model = model.replace("hyperbolic/", "")
            if mapped := self._get_model_map(model):
                model = mapped

            # 2. Context & Tool Extraction
            ctx = self._set_up_context_window(assistant_id, thread_id, trunk=True)

            if not api_key:
                yield json.dumps({"type": "error", "content": "Missing API key."})
                return

            client = self._get_hyperbolic_client(
                api_key=api_key, base_url=os.getenv("HYPERBOLIC_BASE_URL")
            )

            payload = {
                "messages": ctx,
                "model": model,
                "temperature": kwargs.get("temperature", 0.6),
                "top_p": 0.9,
                "stream": True,
            }

            async_stream = client.stream_chat_completion(**payload)

            yield json.dumps({"type": "status", "status": "started", "run_id": run_id})

            assistant_reply = ""
            reasoning_reply = ""

            # Helper for constructing JSON string manually in 'accumulated'
            accumulated = ""
            is_native_tool_call = False
            current_tool_name: str | None = None
            current_tool_args_buffer: str = ""

            token_iterator = async_to_sync_stream(async_stream)

            # 4. Standardized Chunk Processing
            for chunk in HyperbolicDeltaNormalizer.iter_deltas(token_iterator, run_id):
                if stop_event.is_set():
                    break

                ctype, ccontent = chunk["type"], chunk["content"]

                if ctype == "content":
                    assistant_reply += ccontent

                elif ctype == "tool_name":
                    # Detected start of Native tool call
                    is_native_tool_call = True
                    current_tool_name = ccontent
                    # Start building the JSON structure for history
                    accumulated += f'{{"name": "{ccontent}", "arguments": '

                elif ctype == "call_arguments":
                    # Simply append raw JSON arguments to buffers
                    if is_native_tool_call:
                        current_tool_args_buffer += ccontent
                    accumulated += ccontent

                elif ctype == "tool_call":
                    # Full tool call object received (final check/flush)
                    if isinstance(ccontent, dict):
                        if is_native_tool_call:
                            # We were already streaming, so we trust the stream
                            pass
                        else:
                            # Unexpected full object, append it directly
                            accumulated += json.dumps(ccontent)

                elif ctype == "reasoning":
                    reasoning_reply += ccontent

                yield json.dumps(chunk)
                self._shunt_to_redis_stream(redis, stream_key, chunk)

        except Exception as exc:
            err = {"type": "error", "content": f"Llama stream error: {exc}"}
            yield json.dumps(err)
            self._shunt_to_redis_stream(redis, stream_key, err)
        finally:
            # Ensure JSON is valid in history if tool call was interrupted or finished
            # This closes the string we opened in 'tool_name'
            if is_native_tool_call and accumulated:
                stripped = accumulated.strip()
                if not stripped.endswith("}"):
                    accumulated += "}"
            stop_event.set()

        # 5. FINAL CLOSE-OUT & SMART HISTORY PRESERVATION
        yield json.dumps({"type": "status", "status": "complete", "run_id": run_id})

        # Check for function calls to determine what to save
        has_fc = self.parse_and_set_function_calls(accumulated, assistant_reply)

        # Save 'accumulated' (raw JSON string) if tool was triggered, else content
        message_to_save = accumulated if has_fc else assistant_reply

        if not message_to_save:
            message_to_save = assistant_reply

        if message_to_save:
            self.finalize_conversation(message_to_save, thread_id, assistant_id, run_id)

        if has_fc:
            self.project_david_client.runs.update_run_status(
                run_id, StatusEnum.pending_action.value
            )
        else:
            self.project_david_client.runs.update_run_status(
                run_id, StatusEnum.completed.value
            )

    def process_conversation(
        self,
        thread_id: str,
        message_id: Optional[str],
        run_id: str,
        assistant_id: str,
        model: Any,
        api_key: Optional[str] = None,
        **kwargs,
    ):
        # Step 1: Initial Response / Tool Trigger
        yield from self.stream(
            thread_id,
            message_id,
            run_id,
            assistant_id,
            model,
            api_key=api_key,
            **kwargs,
        )

        # Step 2: Follow-up if a function call was detected
        if self.get_function_call_state():
            yield from self.process_tool_calls(
                thread_id, run_id, assistant_id, model=model, api_key=api_key
            )
            self.set_tool_response_state(False)
            self.set_function_call_state(None)

            # Re-stream with the tool result in the history context
            yield from self.stream(
                thread_id, None, run_id, assistant_id, model, api_key=api_key, **kwargs
            )
