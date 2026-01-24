from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Generator, Optional

from dotenv import load_dotenv
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from src.api.entities_api.dependencies import get_redis
from src.api.entities_api.orchestration.engine.orchestrator_core import OrchestratorCore
from src.api.entities_api.orchestration.mixins import (
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
from src.api.entities_api.orchestration.streaming.hyperbolic import (
    HyperbolicDeltaNormalizer,
)

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


class LlamaBaseWorker(_ProviderMixins, OrchestratorCore, ABC):
    """
    Abstract Base for Llama-3.3 Providers (Hyperbolic, Together, etc.).
    """

    def __init__(
        self, *, assistant_id=None, thread_id=None, redis=None, **extra
    ) -> None:
        self._assistant_cache = extra.get("assistant_cache") or {}
        self.redis = redis or get_redis()
        self.assistant_id = assistant_id
        self.thread_id = thread_id
        self.api_key = extra.get("api_key")

        self.model_name = extra.get("model_name", "meta-llama/Llama-3.3-70B-Instruct")
        self.max_context_window = extra.get("max_context_window", 128000)
        self.threshold_percentage = extra.get("threshold_percentage", 0.8)

        self.setup_services()
        LOG.debug(f"{self.__class__.__name__} ready (assistant={assistant_id})")

    @abstractmethod
    def _get_client_instance(self, api_key: str):
        """Return the specific provider client."""
        pass

    @abstractmethod
    def _execute_stream_request(self, client, payload: dict) -> Any:
        """
        Execute the stream request.
        Hyperbolic uses async_to_sync wrapper, Together uses standard sync.
        """
        pass

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
        *,
        force_refresh: bool = False,
        stream_reasoning: bool = False,
        api_key: Optional[str] = None,
        **kwargs,
    ) -> Generator[str, None, None]:
        redis = get_redis()
        stream_key = f"stream:{run_id}"
        stop_event = self.start_cancellation_monitor(run_id)

        # Use instance key if not provided
        api_key = api_key or self.api_key

        try:
            # 1. Clean Model ID
            if isinstance(model, str) and model.startswith("hyperbolic/"):
                model = model.replace("hyperbolic/", "")
            if mapped := self._get_model_map(model):
                model = mapped

            # 2. Context & Tool Extraction
            raw_ctx = self._set_up_context_window(
                assistant_id,
                thread_id,
                trunk=True,
                structured_tool_call=True,
                force_refresh=force_refresh,
            )

            cleaned_ctx, extracted_tools = self.prepare_native_tool_context(raw_ctx)

            if not api_key:
                yield json.dumps({"type": "error", "content": "Missing API key."})
                return

            client = self._get_client_instance(api_key=api_key)

            payload = {
                "messages": cleaned_ctx,
                "tools": extracted_tools,
                "model": model,
                "temperature": kwargs.get("temperature", 0.6),
                "top_p": 0.9,
                "stream": True,
            }

            # 3. Get the iterator (Abstracted)
            raw_stream = self._execute_stream_request(client, payload)

            yield json.dumps({"type": "status", "status": "started", "run_id": run_id})

            # State Tracking
            assistant_reply = ""
            reasoning_reply = ""
            accumulated = ""
            is_native_tool_call = False
            current_tool_args_buffer = ""

            # 4. Standardized Chunk Processing (Universal Normalizer)
            for chunk in HyperbolicDeltaNormalizer.iter_deltas(raw_stream, run_id):
                if stop_event.is_set():
                    break

                ctype, ccontent = chunk["type"], chunk["content"]

                if ctype == "content":
                    assistant_reply += ccontent

                elif ctype == "tool_name":
                    is_native_tool_call = True
                    # Start manually building JSON for history preservation
                    accumulated += f'{{"name": "{ccontent}", "arguments": '

                elif ctype == "call_arguments":
                    if is_native_tool_call:
                        current_tool_args_buffer += ccontent
                    accumulated += ccontent

                elif ctype == "tool_call":
                    # Full tool call object (Legacy/Fallback)
                    if isinstance(ccontent, dict) and not is_native_tool_call:
                        accumulated += json.dumps(ccontent)

                elif ctype == "reasoning":
                    reasoning_reply += ccontent

                yield json.dumps(chunk)
                self._shunt_to_redis_stream(redis, stream_key, chunk)

        except Exception as exc:
            err = {"type": "error", "content": f"Stream error: {exc}"}
            yield json.dumps(err)
            self._shunt_to_redis_stream(redis, stream_key, err)
        finally:
            # Fix broken JSON structure if stream ended abruptly inside a tool call
            if is_native_tool_call and accumulated:
                stripped = accumulated.strip()
                if not stripped.endswith("}"):
                    accumulated += "}"
            stop_event.set()

        # 5. Final Close-out & Preservation
        yield json.dumps({"type": "status", "status": "complete", "run_id": run_id})

        has_fc = self.parse_and_set_function_calls(accumulated, assistant_reply)
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
        self, thread_id, message_id, run_id, assistant_id, model, api_key=None, **kwargs
    ):
        """Standard Llama process loop."""
        yield from self.stream(
            thread_id,
            message_id,
            run_id,
            assistant_id,
            model,
            api_key=api_key,
            **kwargs,
        )

        if self.get_function_call_state():
            yield from self.process_tool_calls(
                thread_id, run_id, assistant_id, model=model, api_key=api_key
            )
            self.set_tool_response_state(False)
            self.set_function_call_state(None)

            yield from self.stream(
                thread_id, None, run_id, assistant_id, model, api_key=api_key, **kwargs
            )
