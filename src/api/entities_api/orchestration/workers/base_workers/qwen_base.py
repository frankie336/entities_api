# src/api/entities_api/workers/qwen_worker.py
from __future__ import annotations

import asyncio
import json
import os
import uuid
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, Optional, Union

from dotenv import load_dotenv
from projectdavid import StreamEvent
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from entities_api.cache.assistant_cache import AssistantCache
from entities_api.clients.delta_normalizer import DeltaNormalizer
from entities_api.utils.assistant_manager import AssistantManager
from entities_api.utils.delegation_model_map import get_delegated_model
# --- DEPENDENCIES ---
from src.api.entities_api.dependencies import get_redis, get_redis_sync
from src.api.entities_api.orchestration.engine.orchestrator_core import \
    OrchestratorCore
# --- MIXINS ---
from src.api.entities_api.orchestration.mixins.provider_mixins import \
    _ProviderMixins

load_dotenv()
LOG = LoggingUtility()


class QwenBaseWorker(
    _ProviderMixins,
    OrchestratorCore,
    ABC,
):
    """
    Async Base for Qwen Providers (Hyperbolic, Together, etc.).
    Handles QwQ-32B/Qwen2.5/Kimi specific stream parsing using DeltaNormalizer.
    """

    def __init__(
        self,
        *,
        assistant_id: str | None = None,
        thread_id: str | None = None,
        redis=None,
        base_url: str | None = None,
        api_key: str | None = None,
        delete_ephemeral_thread: bool = False,
        assistant_cache_service: Optional[AssistantCache] = None,
        **extra,
    ) -> None:

        # 1. Config & Dependencies
        self.api_key = api_key or extra.get("api_key")
        # ephemeral worker config
        # These objects are used for deep search
        self.is_deep_research = None
        self._delete_ephemeral_thread = delete_ephemeral_thread or extra.get(
            "delete_ephemeral_thread"
        )
        self.ephemeral_supervisor_id = None
        self._delegation_api_key = self.api_key

        self.redis = redis or get_redis_sync()

        # 2. Cache Service Setup
        if assistant_cache_service:
            self._assistant_cache = assistant_cache_service
        elif "assistant_cache" in extra and isinstance(
            extra["assistant_cache"], AssistantCache
        ):
            self._assistant_cache = extra["assistant_cache"]

        # 3. Config Legacy Support
        legacy_config = extra.get("assistant_config") or extra.get("assistant_cache")
        self.assistant_config: Dict[str, Any] = (
            legacy_config if isinstance(legacy_config, dict) else {}
        )

        self._david_client: Any = None
        self.assistant_id = assistant_id
        self.thread_id = thread_id
        self.base_url = base_url or os.getenv("BASE_URL")

        self.model_name = extra.get("model_name", "qwen/Qwen1_5-32B-Chat")
        self.max_context_window = extra.get("max_context_window", 128000)
        self.threshold_percentage = extra.get("threshold_percentage", 0.8)

        # 4. State Tracking
        self._current_tool_call_id: str | None = None
        self._pending_tool_payload: Optional[Dict[str, Any]] = None
        self._decision_payload: Optional[Dict[str, Any]] = None

        self.setup_services()

        # 5. Mixin Safety Stub
        if not hasattr(self, "get_function_call_state"):
            LOG.error("CRITICAL: ToolRoutingMixin failed to load.")
            self.get_function_call_state = lambda: None
            self.set_function_call_state = lambda x: None
            self.set_tool_response_state = lambda x: None

        LOG.debug(f"{self.__class__.__name__} ready (assistant={assistant_id})")

    @abstractmethod
    def _get_client_instance(self, api_key: str):
        pass

    async def stream(
        self,
        thread_id: str,
        message_id: str | None,
        run_id: str,
        assistant_id: str,
        model: Any,
        *,
        force_refresh: bool = False,
        stream_reasoning: bool = True,
        api_key: str | None = None,
        **kwargs,
    ) -> AsyncGenerator[Union[str, StreamEvent], None]:
        """
        Level 4 Deep Research Stream.
        Utilizes DeltaNormalizer for Qwen/Kimi tag handling and helper method for state management.
        """
        # -----------------------------------
        # Ephemeral supervisor
        # -----------------------------------
        self.ephemeral_supervisor_id = None
        self._delegation_api_key = api_key

        redis = self.redis
        stream_key = f"stream:{run_id}"
        stop_event = self.start_cancellation_monitor(run_id)

        # --- 1. State Initialization ---
        self._current_tool_call_id = None
        self._decision_payload = None
        self._tool_queue = []

        accumulated: str = ""
        assistant_reply: str = ""
        decision_buffer: str = ""
        current_block: str | None = None

        try:
            # --- 2. Model & Identity Setup ---
            if hasattr(self, "_get_model_map") and (
                mapped := self._get_model_map(model)
            ):
                model = mapped

            self.assistant_id = assistant_id
            await self._ensure_config_loaded()

            # Check for Deep Research / Supervisor Mode
            self.is_deep_research = self.assistant_config.get("deep_research", False)

            if self.is_deep_research:
                LOG.critical(
                    "██████ [DEEP_RESEARCH_MODE]=%s ██████", self.is_deep_research
                )
                assistant_manager = AssistantManager()
                ephemeral_supervisor = (
                    await assistant_manager.create_ephemeral_supervisor()
                )
                self.assistant_id = ephemeral_supervisor.id
                self.ephemeral_supervisor_id = ephemeral_supervisor.id

                # set the delegated inference model for deep search
                self._delegation_model = get_delegated_model(requested_model=model)

            agent_mode_setting = self.assistant_config.get("agent_mode", False)
            decision_telemetry = self.assistant_config.get("decision_telemetry", False)
            web_access_setting = self.assistant_config.get("decision_telemetry", False)

            # --- 3. Context & Client ---
            ctx = await self._set_up_context_window(
                assistant_id=self.assistant_id,
                thread_id=thread_id,
                trunk=True,
                force_refresh=force_refresh,
                agent_mode=agent_mode_setting,
                decision_telemetry=decision_telemetry,
                web_access=web_access_setting,
                deep_research=self.is_deep_research,
            )

            if not api_key:
                yield json.dumps({"type": "error", "content": "Missing API key."})
                return

            yield json.dumps({"type": "status", "status": "started", "run_id": run_id})

            client = self._get_client_instance(api_key=api_key)

            # --- 4. The Stream Loop ---
            raw_stream = client.stream_chat_completion(
                messages=ctx,
                model=model,
                max_tokens=10000,
                temperature=kwargs.get("temperature", 0.6),
                stream=True,
            )

            async for chunk in DeltaNormalizer.async_iter_deltas(raw_stream, run_id):
                if stop_event.is_set():
                    break

                # Delegate state management to helper
                (
                    current_block,
                    accumulated,
                    assistant_reply,
                    decision_buffer,
                    should_skip,
                ) = self._handle_chunk_accumulation(
                    chunk, current_block, accumulated, assistant_reply, decision_buffer
                )

                if should_skip:
                    continue

                yield json.dumps(chunk)
                await self._shunt_to_redis_stream(redis, stream_key, chunk)

            # Ensure any dangling XML tag is closed at the end of stream
            if current_block:
                accumulated += f"</{current_block}>"

        except Exception as exc:
            LOG.error(f"Stream Exception: {exc}")
            yield json.dumps({"type": "error", "content": str(exc), "run_id": run_id})
        finally:

            # 1. Ensure cancellation monitor is stopped
            stop_event.set()
            # 2. Ephemeral Assistant Cleanup
            if self.ephemeral_supervisor_id:

                # We use the helper method we wrote earlier, ensuring 'await' is used
                await self._ephemeral_clean_up(
                    assistant_id=self.ephemeral_supervisor_id,
                    thread_id=thread_id,
                    delete_thread=False,
                )

        # --- 5. Post-Stream: Parse Decision & Tools ---

        # 5a. Extract Decision Payload (if available)
        if decision_buffer:
            try:
                self._decision_payload = json.loads(decision_buffer.strip())
            except Exception:
                LOG.warning(
                    f"Failed to parse decision buffer: {decision_buffer[:50]}..."
                )

        # 5b. Extract Tool Calls (DeltaNormalizer has already normalized them to 'call_arguments')
        # This parses the 'accumulated' XML/string into a list of dictionaries
        tool_calls_batch = self.parse_and_set_function_calls(
            accumulated, assistant_reply
        )

        message_to_save = assistant_reply
        final_status = StatusEnum.completed.value

        # --- 6. Tool Handling & Envelope Creation ---
        if tool_calls_batch:
            self._tool_queue = tool_calls_batch
            final_status = StatusEnum.pending_action.value

            # Build Standardized Tool Envelope (ID Parity for Turn 2)
            tool_calls_structure = []
            for tool in tool_calls_batch:
                t_id = tool.get("id") or f"call_{uuid.uuid4().hex[:8]}"
                tool_calls_structure.append(
                    {
                        "id": t_id,
                        "type": "function",
                        "function": {
                            "name": tool.get("name"),
                            "arguments": json.dumps(tool.get("arguments", {})),
                        },
                    }
                )

            # Save the STRUCTURAL representation, not the raw text
            message_to_save = json.dumps(tool_calls_structure)
            yield json.dumps(
                {"type": "status", "status": "processing", "run_id": run_id}
            )

        # --- 7. Finalize & Persist ---
        if message_to_save:
            await self.finalize_conversation(
                message_to_save, thread_id, self.assistant_id, run_id
            )

        # Update Run status in DB
        if self.project_david_client:
            await asyncio.to_thread(
                self.project_david_client.runs.update_run_status, run_id, final_status
            )

        if not tool_calls_batch:
            yield json.dumps({"type": "status", "status": "complete", "run_id": run_id})
