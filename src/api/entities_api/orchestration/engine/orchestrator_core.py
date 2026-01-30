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
from entities_api.orchestration.streaming.hyperbolic import \
    HyperbolicDeltaNormalizer
from src.api.entities_api.orchestration.mixins.client_factory_mixin import \
    ClientFactoryMixin
from src.api.entities_api.orchestration.mixins.code_execution_mixin import \
    CodeExecutionMixin
from src.api.entities_api.orchestration.mixins.consumer_tool_handlers_mixin import \
    ConsumerToolHandlersMixin
from src.api.entities_api.orchestration.mixins.conversation_context_mixin import \
    ConversationContextMixin
from src.api.entities_api.orchestration.mixins.json_utils_mixin import \
    JsonUtilsMixin
from src.api.entities_api.orchestration.mixins.platform_tool_handlers_mixin import \
    PlatformToolHandlersMixin
from src.api.entities_api.orchestration.mixins.service_registry_mixin import \
    ServiceRegistryMixin
from src.api.entities_api.orchestration.mixins.shell_execution_mixin import \
    ShellExecutionMixin
from src.api.entities_api.orchestration.mixins.streaming_mixin import \
    StreamingMixin
from src.api.entities_api.orchestration.mixins.tool_routing_mixin import \
    ToolRoutingMixin

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

    @abstractmethod
    def _get_client_instance(self, api_key: str):
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
        stream_reasoning: bool = True,
        api_key: Optional[str] = None,
        **kwargs,
    ) -> Generator[str, None, None]:
        redis = get_redis()
        stream_key = f"stream:{run_id}"
        stop_event = self.start_cancellation_monitor(run_id)

        self._current_tool_call_id = None
        # Reset handover state
        self._pending_tool_payload = None

        accumulated: str = ""
        assistant_reply: str = ""
        reasoning_reply: str = ""
        current_block: str | None = None

        try:
            if mapped := self._get_model_map(model):
                model = mapped

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

            client = self._get_client_instance(api_key=api_key)
            raw_stream = client.chat.completions.create(**payload)

            for chunk in HyperbolicDeltaNormalizer.iter_deltas(raw_stream, run_id):
                if stop_event.is_set():
                    break

                ctype, ccontent = chunk["type"], chunk["content"]

                # --- 1. STATE MANAGEMENT (Keep this exactly as is) ---
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

                accumulated += ccontent

                # --- 2. SELECTIVE YIELDING ---
                # We STOP yielding call_arguments directly to the client
                if ctype == "call_arguments":
                    continue

                    # We yield everything else (content, reasoning, etc)
                yield json.dumps(chunk)
                self._shunt_to_redis_stream(redis, stream_key, chunk)

            # Close tags
            if current_block == "fc":
                accumulated += "</fc>"
            elif current_block == "think":
                accumulated += "</think>"

            yield json.dumps(
                {"type": "status", "status": "processing", "run_id": run_id}
            )

            # --- 3. PERSISTENCE & HANDOVER PREP ---
            has_fc = self.parse_and_set_function_calls(accumulated, assistant_reply)
            message_to_save = assistant_reply

            if has_fc:
                try:
                    # Clean tags
                    raw_json = (
                        accumulated.replace("<fc>", "").replace("</fc>", "").strip()
                    )
                    payload_dict = json.loads(raw_json)
                    message_to_save = json.dumps(payload_dict)

                    # [CRITICAL] Store the payload for the next step (process_conversation)
                    self._pending_tool_payload = payload_dict

                except Exception as e:
                    LOG.error(f"Error parsing raw tool JSON: {e}")
                    message_to_save = accumulated

            if message_to_save:
                self.finalize_conversation(
                    message_to_save, thread_id, assistant_id, run_id
                )

            if has_fc:
                self.project_david_client.runs.update_run_status(
                    run_id, StatusEnum.pending_action.value
                )
            else:
                self.project_david_client.runs.update_run_status(
                    run_id, StatusEnum.completed.value
                )
                # Only yield 'complete' if no tool call.
                # If tool call, the tool processor will yield manifests then complete.
                yield json.dumps(
                    {"type": "status", "status": "complete", "run_id": run_id}
                )

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
