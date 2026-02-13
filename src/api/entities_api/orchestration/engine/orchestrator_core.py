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
import uuid
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

# -------------------------------------------------------------------------
# IMPORTS
# -------------------------------------------------------------------------
from projectdavid import StreamEvent
from projectdavid_common import \
    ToolValidator  # Assumed available based on snippet
from projectdavid_common.schemas.enums import StatusEnum
from projectdavid_common.utilities.logging_service import LoggingUtility

from entities_api.cache.assistant_cache import AssistantCache
from entities_api.dependencies import get_redis_sync
from src.api.entities_api.constants.assistant import PLATFORM_TOOLS
# Mixins
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

    def __init__(
        self,
        *,
        assistant_id: str | None = None,
        thread_id: str | None = None,
        redis=None,
        base_url: str | None = None,
        api_key: str | None = None,
        assistant_cache_service: Optional[AssistantCache] = None,
        **extra,
    ) -> None:

        # 1. Setup Redis (Critical for the Mixin fallback)
        self.redis = redis or get_redis_sync()

        # 2. Setup the Cache Service
        if assistant_cache_service:
            self._assistant_cache = assistant_cache_service
        elif "assistant_cache" in extra and isinstance(
            extra["assistant_cache"], AssistantCache
        ):
            self._assistant_cache = extra["assistant_cache"]

        # 3. Setup the Data/Config
        legacy_config = extra.get("assistant_config") or extra.get("assistant_cache")
        self.assistant_config: Dict[str, Any] = (
            legacy_config if isinstance(legacy_config, dict) else {}
        )

        # 4. Core State
        self._current_tool_call_id: Optional[str] = None
        self._decision_payload: Any = None

    """
    All behaviour resides in the mix-ins.
    Concrete provider classes only need to implement:
        • stream()
    """

    tool_response: Optional[bool] = None
    function_call: Optional[dict] = None
    _cancelled: bool = False
    code_mode: bool = False

    # --------------------------------------------------------------------------
    # ABSTRACT METHODS
    # --------------------------------------------------------------------------

    @abstractmethod
    def _get_client_instance(self, api_key: str):
        """Return the specific provider client."""
        pass

    @abstractmethod
    def _execute_stream_request(self, client, payload: dict) -> Any:
        """Execute the stream request (Sync or Async-to-Sync)."""
        pass

    @abstractmethod
    async def stream(
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
    ) -> AsyncGenerator[str, None]:
        """
        Must open a streaming connection to the underlying LLM provider,
        parse deltas into the mix-in JSON chunk format and `yield` them.
        """
        yield ""

    # --------------------------------------------------------------------------
    # CONFIG HELPERS
    # --------------------------------------------------------------------------

    @property
    def assistant_cache(self) -> dict:
        return self._assistant_cache

    @assistant_cache.setter
    def assistant_cache(self, value: dict) -> None:
        self._assistant_cache = value

    def get_assistant_cache(self) -> dict:
        return self._assistant_cache

    async def load_assistant_config(self):
        """
        Populates self.assistant_config from Redis if not already set.
        """
        if not self.assistant_config and self.assistant_id:
            self.assistant_config = (
                await self.assistant_cache.retrieve(self.assistant_id) or {}
            )
            LOG.debug(f"Loaded config for {self.assistant_id}")

    async def _ensure_config_loaded(self):
        """
        Forces a cache refresh from Redis.
        """
        if not self.assistant_id:
            LOG.warning("⚠️ Cannot load config: No assistant_id provided.")
            return

        try:
            cached_data = await self.assistant_cache.retrieve(self.assistant_id)
            if cached_data:
                self.assistant_config = cached_data
                LOG.info(
                    f"✅ Config Loaded for {self.assistant_id} | "
                    f"AgentMode: {self.assistant_config.get('agent_mode')}"
                )
            else:
                LOG.warning(f"⚠️ Cache Miss for {self.assistant_id}")
        except Exception as e:
            LOG.error(f"❌ Error loading assistant config: {e}")

    def _build_tool_structure(self, batch):
        """Helper to format tool calls for history."""
        structure = []
        for tool in batch:
            tool_id = tool.get("id") or f"call_{uuid.uuid4().hex[:8]}"
            structure.append(
                {
                    "id": tool_id,
                    "type": "function",
                    "function": {
                        "name": tool.get("name"),
                        "arguments": (
                            json.dumps(tool.get("arguments", {}))
                            if isinstance(tool.get("arguments"), dict)
                            else tool.get("arguments")
                        ),
                    },
                }
            )
        return structure

    # --------------------------------------------------------------------------
    # CORE ORCHESTRATION LOOP (Recursive Level 3)
    # --------------------------------------------------------------------------

    async def process_conversation(
        self,
        thread_id: str,
        message_id: Optional[str],
        run_id: str,
        assistant_id: str,
        model: Any,
        api_key: Optional[str] = None,
        max_turns: int = 30,
        **kwargs,
    ) -> AsyncGenerator[Union[str, StreamEvent], None]:
        """
        Level 3 Recursive Orchestrator (Batch-Aware).

        Logic Flow:
        1. Stream LLM tokens.
        2. Check for tool calls.
        3. If NO tools -> Finish.
        4. If tools -> Execute tools -> Loop back to Step 1 (Recursion).
        """

        # Ensure config is ready
        await self._ensure_config_loaded()

        tool_validator = ToolValidator()
        turn_count = 0
        current_message_id = message_id

        while turn_count < max_turns:
            turn_count += 1
            LOG.info(f"ORCHESTRATOR ▸ Turn {turn_count} start [Run: {run_id}]")

            # ------------------------------------------------------------------
            # 1. RESET INTERNAL TURN STATE
            # ------------------------------------------------------------------
            self.set_tool_response_state(False)
            self.set_function_call_state(None)
            self._current_tool_call_id = None

            # ------------------------------------------------------------------
            # 2. INFERENCE TURN (STREAM MODEL OUTPUT)
            # ------------------------------------------------------------------
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

            # ------------------------------------------------------------------
            # 3. CHECK FOR TOOLS
            # ------------------------------------------------------------------
            # Retrieves the list of tool calls accumulated by the Mixins during stream()
            batch: List[Dict] = self.get_function_call_state()

            if not batch:
                # No tools called = Final text response. We are done.
                LOG.info(f"ORCHESTRATOR ▸ Turn {turn_count} completed with text.")
                break

            # ------------------------------------------------------------------
            # 4. TOOL ARGUMENT VALIDATION GATE
            # ------------------------------------------------------------------
            for call in batch:
                tool_name = call.get("name")
                args = call.get("arguments", {})

                # Validate structure of arguments before execution
                validation_event = tool_validator.validate_args(
                    tool_name=tool_name,
                    args=args,
                )

                # FIXED: Only yield if there is an actual error/event.
                # If validation passes, validation_event is None.
                if validation_event:
                    yield validation_event

            # Check if we have "Consumer Tools" (External SDK tools) vs "Platform Tools" (Internal)
            has_consumer_tool = any(
                call.get("name") not in PLATFORM_TOOLS for call in batch
            )

            # ------------------------------------------------------------------
            # 5. TOOL EXECUTION TURN
            # ------------------------------------------------------------------
            # This yields the output of the tools (e.g., "Scanning code...")
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

            # ------------------------------------------------------------------
            # 6. RECURSION DECISION
            # ------------------------------------------------------------------
            if not has_consumer_tool:
                # If we only ran Platform Tools (Files, Search, etc.), we recurse immediately
                # to let the LLM see the output and formulate a response.
                LOG.info(
                    f"ORCHESTRATOR ▸ Platform batch {turn_count} complete. Looping..."
                )

                # Small sleep to prevent tight loop race conditions in some DBs
                await asyncio.sleep(0.5)

                # Reset message_id so the provider fetches the *updated* thread history
                current_message_id = None
                continue

            # If a Consumer Tool was called (e.g. client-side action), we stop here
            # and let the SDK handle the rest.
            LOG.info(f"ORCHESTRATOR ▸ Consumer tool detected. Handing over to SDK.")
            return

        # ----------------------------------------------------------------------
        # FAILSAFE
        # ----------------------------------------------------------------------
        if turn_count >= max_turns:
            LOG.error("ORCHESTRATOR ▸ Max turns reached.")
            yield json.dumps(
                {"type": "error", "content": "Maximum conversation turns exceeded"}
            )
