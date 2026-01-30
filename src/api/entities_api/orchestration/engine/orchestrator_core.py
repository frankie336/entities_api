"""
orchestrator_core.py
────────────────────
The ultra-thin root class.

• Glues together every functional mix-in in the correct MRO order
• Carries only a few shared state fields
• Leaves `stream` + `process_conversation` abstract so each provider
  (Hyperbolic, OpenAI, Together, …) can implement its own wire-format.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Generator, Optional

from projectdavid_common.schemas.enums import StatusEnum
from projectdavid_common.utilities.logging_service import LoggingUtility

from entities_api.dependencies import get_redis
from entities_api.orchestration.streaming.hyperbolic import HyperbolicDeltaNormalizer
from src.api.entities_api.orchestration.mixins.client_factory_mixin import ClientFactoryMixin
from src.api.entities_api.orchestration.mixins.code_execution_mixin import CodeExecutionMixin
from src.api.entities_api.orchestration.mixins.consumer_tool_handlers_mixin import (
    ConsumerToolHandlersMixin,
)
from src.api.entities_api.orchestration.mixins.conversation_context_mixin import (
    ConversationContextMixin,
)
from src.api.entities_api.orchestration.mixins.json_utils_mixin import JsonUtilsMixin
from src.api.entities_api.orchestration.mixins.platform_tool_handlers_mixin import (
    PlatformToolHandlersMixin,
)
from src.api.entities_api.orchestration.mixins.service_registry_mixin import ServiceRegistryMixin
from src.api.entities_api.orchestration.mixins.shell_execution_mixin import ShellExecutionMixin
from src.api.entities_api.orchestration.mixins.streaming_mixin import StreamingMixin
from src.api.entities_api.orchestration.mixins.tool_routing_mixin import ToolRoutingMixin

LOG = LoggingUtility()


class OrchestratorCore(
    ClientFactoryMixin,
    ServiceRegistryMixin,
    JsonUtilsMixin,
    ConversationContextMixin,
    ToolRoutingMixin,
    PlatformToolHandlersMixin,
    ConsumerToolHandlersMixin,
    StreamingMixin,
    CodeExecutionMixin,
    ShellExecutionMixin,
    ABC,
):
    """
    All behaviour resides in the mix-ins.
    Concrete provider classes only need to implement:

        • stream()
        • process_conversation()

    Everything else (tool routing, history, JSON hygiene, …) is inherited.
    """

    tool_response: Optional[bool] = None
    function_call: Optional[dict] = None
    _cancelled: bool = False
    code_mode: bool = False

    def __init__(self):
        self.api_key = None

    @abstractmethod
    def _get_client_instance(self, api_key: str):
        """Return the specific provider client."""
        pass

    @abstractmethod
    def _execute_stream_request(self, client, payload: dict) -> Any:
        """Execute the stream request (Sync or Async-to-Sync)."""
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
        stream_reasoning: bool = False,
        api_key: Optional[str] = None,
        **kwargs,
    ) -> Generator[str, None, None]:
        redis = get_redis()
        stream_key = f"stream:{run_id}"
        stop_event = self.start_cancellation_monitor(run_id)

        # Use instance key if not provided
        api_key = api_key or self.api_key

        # --- FIX 1: Early Variable Initialization (Safety) ---
        assistant_reply = ""
        accumulated = ""
        reasoning_reply = ""
        current_block = None
        # -----------------------------------------------------

        try:
            if mapped := self._get_model_map(model):
                model = mapped

            # 1. Context Window Setup
            ctx = self._set_up_context_window(assistant_id, thread_id, trunk=True)

            payload = {
                "model": model,
                "messages": ctx,
                "max_tokens": 10000,
                "temperature": kwargs.get("temperature", 0.6),
                "stream": True,
            }

            start_chunk = {"type": "status", "status": "started", "run_id": run_id}
            yield json.dumps(start_chunk)
            self._shunt_to_redis_stream(redis, stream_key, start_chunk)

            # -----------------------------------------------------------
            # DYNAMIC CLIENT EXECUTION
            # -----------------------------------------------------------
            client = self._get_client_instance(api_key=api_key)
            raw_stream = self._execute_stream_request(client, payload)
            # -----------------------------------------------------------

            # 2. Process deltas via Shared Normalizer
            for chunk in HyperbolicDeltaNormalizer.iter_deltas(raw_stream, run_id):
                if stop_event.is_set():
                    break

                ctype, ccontent = chunk["type"], chunk["content"]

                # --- HISTORY RECONSTRUCTION (Tag Injection) ---
                if ctype == "content":
                    if current_block == "fc":
                        accumulated += "</fc>"
                    elif current_block == "think":
                        accumulated += "</think>"
                    current_block = None
                    assistant_reply += ccontent

                elif ctype == "call_arguments":
                    if current_block != "fc":
                        if current_block == "think":
                            accumulated += "</think>"
                        accumulated += "<fc>"
                        current_block = "fc"

                elif ctype == "reasoning":
                    if current_block != "think":
                        if current_block == "fc":
                            accumulated += "</fc>"
                        accumulated += "<think>"
                        current_block = "think"
                    reasoning_reply += ccontent

                # Accumulate raw stream for persistence
                accumulated += ccontent

                # --- REFACTOR: Prevent yielding ANY tool artifacts ---
                # We block both 'tool_name' and 'call_arguments' to prevent
                # the client SDK from auto-creating a ghost event with no ID.
                if ctype not in ("tool_name", "call_arguments"):
                    yield json.dumps(chunk)
                # -------------------------------------------------

                self._shunt_to_redis_stream(redis, stream_key, chunk)

            # 3. Final Close-out
            if current_block == "fc":
                accumulated += "</fc>"
            elif current_block == "think":
                accumulated += "</think>"

            yield json.dumps({"type": "status", "status": "complete", "run_id": run_id})

            # ------------------------------------------------------------------
            # 💉 FIX 2: TIMEOUT PREVENTION (Keep-Alive Heartbeat)
            # ------------------------------------------------------------------
            # Send a 'processing' signal to reset the client's timeout timer
            # while the server performs the blocking database save.
            yield json.dumps({"type": "status", "status": "processing", "run_id": run_id})

            # ------------------------------------------------------------------
            # 🔒 FIX 3: SAFE PERSISTENCE LOGIC
            # ------------------------------------------------------------------
            has_fc = self.parse_and_set_function_calls(accumulated, assistant_reply)
            message_to_save = assistant_reply

            if has_fc:
                try:
                    # Clean tags for JSON parsing
                    raw_json = accumulated.replace("<fc>", "").replace("</fc>", "").strip()
                    # Validate JSON structure
                    payload_dict = json.loads(raw_json)

                    # Store as clean JSON
                    message_to_save = json.dumps(payload_dict)
                except Exception as e:
                    LOG.error(f"Error structuring tool calls: {e}")
                    # Fallback to accumulated string so no data is lost
                    message_to_save = accumulated

            if message_to_save:
                self.finalize_conversation(message_to_save, thread_id, assistant_id, run_id)

            if has_fc:
                self.project_david_client.runs.update_run_status(
                    run_id, StatusEnum.pending_action.value
                )
            else:
                self.project_david_client.runs.update_run_status(run_id, StatusEnum.completed.value)

        except Exception as exc:
            err = {"type": "error", "content": str(exc)}
            yield json.dumps(err)
            self._shunt_to_redis_stream(redis, stream_key, err)
        finally:
            stop_event.set()

    @abstractmethod
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
        """
        Typical pattern inside an implementation:

            for chunk in self.stream(...):
                yield chunk

            for chunk in self.process_tool_calls(...):
                yield chunk

            # optional: another self.stream(...) round-trip if a tool
            #           produced new user-visible content
        """
