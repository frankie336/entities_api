# src/api/entities_api/orchestration/providers/hypherbolic/base_provider.py

import json
import os
from typing import Any, Generator, Optional
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from src.api.entities_api.dependencies import get_redis
from src.api.entities_api.orchestration.mixins import (
    AssistantCacheMixin, JsonUtilsMixin, ConversationContextMixin,
    ToolRoutingMixin, PlatformToolHandlersMixin, ConsumerToolHandlersMixin,
    CodeExecutionMixin, ShellExecutionMixin, FileSearchMixin
)
from entities_api.orchestration.engine.orchestrator_core import OrchestratorCore

LOG = LoggingUtility()


class _ProviderMixins(
    AssistantCacheMixin, JsonUtilsMixin, ConversationContextMixin,
    ToolRoutingMixin, PlatformToolHandlersMixin, ConsumerToolHandlersMixin,
    CodeExecutionMixin, ShellExecutionMixin, FileSearchMixin
):
    """Flat bundle for all Hyperbolic-based models."""

class BaseHyperbolicProvider(_ProviderMixins, OrchestratorCore):
    def __init__(self, **kwargs):
        self._assistant_cache = kwargs.get("assistant_cache") or {}
        self.redis = kwargs.get("redis") or get_redis()
        self.assistant_id = kwargs.get("assistant_id")
        self.thread_id = kwargs.get("thread_id")
        self.base_url = kwargs.get("base_url") or os.getenv("HYPERBOLIC_BASE_URL")
        self.api_key = kwargs.get("api_key")
        self.setup_services()

    def _get_refined_generator(self, raw_stream: Any, run_id: str) -> Generator[dict, None, None]:
        """Default implementation: Yields content as-is. Overridden by DeepSeek."""
        for token in raw_stream:
            if not token.choices or not token.choices[0].delta: continue
            content = getattr(token.choices[0].delta, "content", "")
            if content:
                yield {"type": "content", "content": content, "run_id": run_id}

    def stream(self, thread_id: str, message_id: Optional[str], run_id: str,
               assistant_id: str, model: Any, **kwargs) -> Generator[str, None, None]:
        redis = get_redis()
        stream_key = f"stream:{run_id}"
        stop_event = self.start_cancellation_monitor(run_id)

        ctx = self._set_up_context_window(assistant_id, thread_id, trunk=True)
        payload = {"model": model, "messages": ctx, "stream": True, "temperature": 0.6}

        # Start Signal
        yield json.dumps({"type": "status", "status": "started", "run_id": run_id})

        try:
            client = self._get_openai_client(base_url=self.base_url, api_key=kwargs.get("api_key"))
            raw_stream = client.chat.completions.create(**payload)
        except Exception as exc:
            yield json.dumps({"type": "error", "content": f"Init failed: {exc}"})
            return

        assistant_reply, accumulated = "", ""

        # This calls the child's specialized generator (e.g., DeepSeek's <fc> filter)
        for chunk in self._get_refined_generator(raw_stream, run_id):
            if stop_event.is_set(): break

            ctype, ccontent = chunk["type"], chunk["content"]
            accumulated += ccontent
            if ctype == "content": assistant_reply += ccontent

            # Yield and Shunt
            yield json.dumps(chunk)
            self._shunt_to_redis_stream(redis, stream_key, chunk)

        # Finalize and Tool Routing
        self.finalize_conversation(assistant_reply, thread_id, assistant_id, run_id)
        if self.parse_and_set_function_calls(accumulated, assistant_reply):
            self.project_david_client.runs.update_run_status(run_id,
                                                             StatusEnum.pending_action.value)
        else:
            self.project_david_client.runs.update_run_status(run_id, StatusEnum.completed.value)

    def process_conversation(self, **kwargs) -> Generator[str, None, None]:
        """
        Required by OrchestratorCore.
        Delegates to the existing stream logic.
        """
        yield from self.stream(**kwargs)
