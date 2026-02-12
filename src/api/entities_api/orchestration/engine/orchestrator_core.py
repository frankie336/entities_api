# src/api/entities_api/orchestration/engine/orchestrator_core.py
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
from typing import Any, AsyncGenerator, Dict, Generator, Optional, Union

from projectdavid import StreamEvent
from projectdavid_common.utilities.logging_service import LoggingUtility

from entities_api.cache.assistant_cache import AssistantCache
from entities_api.dependencies import get_redis_sync
from src.api.entities_api.constants.assistant import PLATFORM_TOOLS
from src.api.entities_api.orchestration.mixins.client_factory_mixin import (
    ClientFactoryMixin,
)
from src.api.entities_api.orchestration.mixins.code_execution_mixin import (
    CodeExecutionMixin,
)
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
from src.api.entities_api.orchestration.mixins.service_registry_mixin import (
    ServiceRegistryMixin,
)
from src.api.entities_api.orchestration.mixins.shell_execution_mixin import (
    ShellExecutionMixin,
)
from src.api.entities_api.orchestration.mixins.streaming_mixin import StreamingMixin
from src.api.entities_api.orchestration.mixins.tool_routing_mixin import (
    ToolRoutingMixin,
)

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

    def __init__(
        self,
        *,
        assistant_id: str | None = None,
        thread_id: str | None = None,
        redis=None,
        base_url: str | None = None,
        api_key: str | None = None,
        # assistant_cache: dict | None = None,
        assistant_cache_service: Optional[AssistantCache] = None,
        **extra,
    ) -> None:

        # 2. Setup Redis (Critical for the Mixin fallback)
        # We use get_redis_sync() if no client is provided, ensuring we have a connection.
        self.redis = redis or get_redis_sync()

        # 3. Setup the Cache Service (The "New Way")
        # If passed explicitly, store it. If not, the Mixin will lazy-load it using self.redis
        if assistant_cache_service:
            self._assistant_cache = assistant_cache_service
        elif "assistant_cache" in extra and isinstance(extra["assistant_cache"], AssistantCache):
            # Handle case where it might be passed via **extra
            self._assistant_cache = extra["assistant_cache"]

        # 4. Setup the Data/Config (The "Old Way" renamed)
        # We rename this to avoid overwriting the Mixin's property.
        # We check if a raw dict was passed in 'extra' (legacy support)
        legacy_config = extra.get("assistant_config") or extra.get("assistant_cache")
        self.assistant_config: Dict[str, Any] = (
            legacy_config if isinstance(legacy_config, dict) else {}
        )

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
        force_refresh: bool = False,
        stream_reasoning: bool = False,
        api_key: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:  # <--- FIXED (Asynchronous)
        """
        Must open a streaming connection to the underlying LLM provider,
        parse deltas into the mix-in JSON chunk format and `yield` them.

        Every provider has its own SDK quirks – This core class contains
        The common logic.
        """

    # 5. Helper to load config asynchronously
    # Call this at the start of your run/execute method
    async def load_assistant_config(self):
        """
        Populates self.assistant_config from Redis if not already set.
        """
        if not self.assistant_config and self.assistant_id:
            # self.assistant_cache is provided by the Mixin
            self.assistant_config = await self.assistant_cache.retrieve(self.assistant_id) or {}
            LOG.debug(f"Loaded config for {self.assistant_id}")

    async def _ensure_config_loaded(self):
        """
        Forces a cache refresh from Redis.
        Logs exactly what is found to help debug 'False' values.
        """
        # If we don't have an ID, we can't load anything
        if not self.assistant_id:
            LOG.warning("⚠️ Cannot load config: No assistant_id provided.")
            return

        # Try to retrieve from Redis via the Cache Service
        try:
            # This uses the mixin to get the cache service, then hits Redis
            cached_data = await self.assistant_cache.retrieve(self.assistant_id)

            if cached_data:
                self.assistant_config = cached_data

                # [DEBUG] Log exactly what we found to catch typo/logic errors
                LOG.info(
                    f"✅ Config Loaded for {self.assistant_id} | "
                    f"AgentMode: {self.assistant_config.get('agent_mode')} | "
                    f"Telemetry: {self.assistant_config.get('decision_telemetry')}"
                )
            else:
                LOG.warning(
                    f"⚠️ Cache Miss for {self.assistant_id} - Using defaults (AgentMode=False)"
                )

        except Exception as e:
            LOG.error(f"❌ Error loading assistant config: {e}")

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
    ) -> AsyncGenerator[Union[str, StreamEvent], None]:  # <--- ALLOW EVENTS
        """
        Level 3 Recursive Orchestrator (Batch-Aware).
        Yields mixed stream of Text Tokens and Structured Events.
        """
        turn_count = 0
        current_message_id = message_id

        while turn_count < max_turns:
            turn_count += 1
            LOG.info(f"ORCHESTRATOR ▸ Turn {turn_count} start [Run: {run_id}]")

            # --- 1. RESET INTERNAL STATE ---
            self.set_tool_response_state(False)
            self.set_function_call_state(None)
            self._current_tool_call_id = None

            # --- 2. THE INFERENCE TURN ---
            try:
                # The 'stream' method might yield strings (LLM tokens) OR Events
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
                LOG.error(f"ORCHESTRATOR ▸ Turn {turn_count} stream failed: {stream_exc}")
                # Return a proper error event if possible, otherwise JSON string
                yield json.dumps({"type": "error", "content": f"Stream failure: {stream_exc}"})
                break

            # --- 3. BATCH EVALUATION ---
            batch = self.get_function_call_state()

            if not batch:
                LOG.info(f"ORCHESTRATOR ▸ Turn {turn_count} completed with text.")
                break

            has_consumer_tool = any(tool.get("name") not in PLATFORM_TOOLS for tool in batch)

            # --- 4. THE TOOL PROCESSING TURN ---
            # This loop receives StatusEvent objects from WebSearchMixin
            async for chunk in self.process_tool_calls(
                thread_id=thread_id,
                run_id=run_id,
                assistant_id=assistant_id,
                tool_call_id=self._current_tool_call_id,
                model=model,
                api_key=api_key,
                decision=self._decision_payload,
            ):
                # We yield the Object directly.
                # The API endpoint must check `isinstance(chunk, StreamEvent)`
                yield chunk

            # --- 5. RECURSION DECISION ---
            if not has_consumer_tool:
                LOG.info(f"ORCHESTRATOR ▸ Platform batch {turn_count} complete. Stabilizing...")
                await asyncio.sleep(0.5)
                current_message_id = None
                continue
            else:
                LOG.info(f"ORCHESTRATOR ▸ Consumer tool detected in batch. Handing over to SDK.")
                return

        if turn_count >= max_turns:
            LOG.error(f"ORCHESTRATOR ▸ Max turns reached.")
