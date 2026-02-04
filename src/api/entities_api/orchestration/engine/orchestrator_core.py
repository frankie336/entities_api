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

import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Generator, Optional

from projectdavid_common.utilities.logging_service import LoggingUtility

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

    @abstractmethod
    def stream(
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
        Must open a streaming connection to the underlying LLM provider,
        parse deltas into the mix-in JSON chunk format and `yield` them.

        Every provider has its own SDK quirks – that's why we leave this
        abstract.
        """

    async def process_conversation(
        self,
        thread_id: str,
        message_id: Optional[str],
        run_id: str,
        assistant_id: str,
        model: Any,
        api_key: Optional[str] = None,
        max_turns: int = 10,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """
        Level 2 Recursive Orchestrator.

        Orchestrates multi-turn self-correction for Platform Tools internally.
        If a Platform Tool (e.g. Code Interpreter) fails with a syntax or logic
        error, this loop injects an instructional hint and re-runs the LLM
        immediately to attempt a fix.
        """
        from src.api.entities_api.constants.assistant import PLATFORM_TOOLS

        turn_count = 0
        current_message_id = message_id  # First turn uses the original user message_id

        while turn_count < max_turns:
            turn_count += 1
            LOG.info(f"ORCHESTRATOR ▸ Turn {turn_count} start [Run: {run_id}]")

            # --- 1. RESET INTERNAL STATE ---
            # Ensure previous turn data doesn't pollute the new turn
            self.set_tool_response_state(False)
            self.set_function_call_state(None)
            self._current_tool_call_id = None

            # --- 2. THE INFERENCE TURN ---
            # Call the LLM and stream the response
            try:
                async for chunk in self.stream(
                    thread_id=thread_id,
                    message_id=current_message_id,
                    run_id=run_id,
                    assistant_id=assistant_id,
                    model=model,
                    # Turn 2+ must force a refresh to include the previous Turn's tool output
                    force_refresh=(turn_count > 1),
                    api_key=api_key,
                    **kwargs,
                ):
                    yield chunk
            except Exception as stream_exc:
                # Catching timeouts (like the one in your logs) to prevent a terminal crash
                LOG.error(
                    f"ORCHESTRATOR ▸ Turn {turn_count} stream failed: {stream_exc}"
                )
                yield json.dumps(
                    {
                        "type": "error",
                        "content": f"Connection error during turn {turn_count}. Sequence aborted.",
                    }
                )
                break

            # After the stream completes, check if a tool call was detected and parsed
            fc_payload = self.get_function_call_state()

            if not fc_payload:
                LOG.info(
                    f"ORCHESTRATOR ▸ Turn {turn_count} produced text. Sequence complete."
                )
                break

            # --- 3. THE TOOL PROCESSING TURN ---
            fc_name = fc_payload.get("name")

            # Dispatch the tool (Direct execution for Platform tools, Manifest for Consumer)
            async for chunk in self.process_tool_calls(
                thread_id=thread_id,
                run_id=run_id,
                assistant_id=assistant_id,
                tool_call_id=self._current_tool_call_id,
                model=model,
                api_key=api_key,
                decision=self._decision_payload,
            ):
                yield chunk

            # --- 4. RECURSION DECISION ---
            if fc_name in PLATFORM_TOOLS:
                # Level 2: Platform tools handle their own turns.
                LOG.info(
                    f"ORCHESTRATOR ▸ Platform tool '{fc_name}' turn complete. Stabilizing..."
                )

                # [STABILIZATION] Give the Database and Assistant Cache a moment to commit
                # the tool output before we refresh context for the next turn.
                # This prevents the 'retrieving run: timed out' error seen in logs.
                await asyncio.sleep(0.5)

                # Turn 2+ relies on thread history, so we clear current_message_id
                current_message_id = None
                continue  # Jumps back to Turn 1 (The Inference Turn)
            else:
                # Consumer tools: The server MUST yield the manifest and close the stream.
                LOG.info(
                    f"ORCHESTRATOR ▸ Consumer tool '{fc_name}' detected. Handover to SDK."
                )
                return

        if turn_count >= max_turns:
            LOG.error(f"ORCHESTRATOR ▸ Max turns ({max_turns}) reached. Terminal exit.")
