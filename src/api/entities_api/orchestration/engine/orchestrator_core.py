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

    async def _ensure_config_loaded(self):
        """
        Ensures self.assistant_config is populated with fresh data from Redis.
        """
        if not self.assistant_config and self.assistant_id:
            # self.assistant_cache is provided by the Mixin
            data = await self.assistant_cache.retrieve(self.assistant_id)
            if data:
                self.assistant_config = data
                LOG.debug(f"Loaded config for {self.assistant_id}: {data.keys()}")

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
        Level 3 Recursive Orchestrator (Batch-Aware).

        Orchestrates multi-turn self-correction for Platform Tools.
        Supports batches of multiple tool calls emitted in a single turn.
        """
        from src.api.entities_api.constants.assistant import PLATFORM_TOOLS

        turn_count = 0
        current_message_id = message_id

        while turn_count < max_turns:
            turn_count += 1
            LOG.info(f"ORCHESTRATOR ▸ Turn {turn_count} start [Run: {run_id}]")

            # --- 1. RESET INTERNAL STATE ---
            self.set_tool_response_state(False)
            self.set_function_call_state(None)  # Clears the list
            self._current_tool_call_id = None

            # --- 2. THE INFERENCE TURN ---
            try:
                async for chunk in self.stream(
                    thread_id=thread_id,
                    message_id=current_message_id,
                    run_id=run_id,
                    assistant_id=assistant_id,
                    model=model,
                    force_refresh=(turn_count > 1),
                    api_key=api_key,
                    **kwargs,
                ):
                    yield chunk
            except Exception as stream_exc:
                LOG.error(
                    f"ORCHESTRATOR ▸ Turn {turn_count} stream failed: {stream_exc}"
                )
                yield json.dumps(
                    {"type": "error", "content": f"Stream failure: {stream_exc}"}
                )
                break

            # --- 3. BATCH EVALUATION ---
            # Retrieve the batch queue (List[Dict])
            batch = self.get_function_call_state()

            if not batch:
                LOG.info(f"ORCHESTRATOR ▸ Turn {turn_count} completed with text.")
                break

            # Determine if we need to hand over to the SDK.
            # If any tool in the batch is NOT in PLATFORM_TOOLS, we must stop looping.
            has_consumer_tool = any(
                tool.get("name") not in PLATFORM_TOOLS for tool in batch
            )

            # --- 4. THE TOOL PROCESSING TURN ---
            # The dispatcher now handles the entire batch internally
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

            # --- 5. RECURSION DECISION ---
            if not has_consumer_tool:
                # All tools in this turn were direct-execution Platform Tools.
                LOG.info(
                    f"ORCHESTRATOR ▸ Platform batch {turn_count} complete. Stabilizing..."
                )

                await asyncio.sleep(0.5)
                current_message_id = None
                continue  # Jumps back to Turn N+1
            else:
                # At least one Consumer Tool was detected.
                # Connection closes so SDK can execute and start Request Turn 2.
                LOG.info(
                    f"ORCHESTRATOR ▸ Consumer tool detected in batch. Handing over to SDK."
                )
                return

        if turn_count >= max_turns:
            LOG.error(f"ORCHESTRATOR ▸ Max turns reached.")
