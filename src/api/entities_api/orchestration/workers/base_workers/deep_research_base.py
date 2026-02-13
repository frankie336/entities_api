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

# --- DEPENDENCIES ---
from src.api.entities_api.dependencies import get_redis, get_redis_sync
from src.api.entities_api.orchestration.engine.orchestrator_core import OrchestratorCore

# --- MIXINS ---
from src.api.entities_api.orchestration.mixins.provider_mixins import _ProviderMixins
from src.api.entities_api.utils.ephemeral_worker_maker import AssistantManager

load_dotenv()
LOG = LoggingUtility()


class DeepResearchBaseWorker(
    _ProviderMixins,
    OrchestratorCore,
    ABC,
):
    """
    Async Base for Qwen Providers (Hyperbolic, Together, etc.).
    Handles QwQ-32B/Qwen2.5 specific stream parsing, history preservation,
    and Deep Research Supervisor capabilities.
    """

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
        self.redis = redis or get_redis_sync()

        if assistant_cache_service:
            self._assistant_cache = assistant_cache_service
        elif "assistant_cache" in extra and isinstance(extra["assistant_cache"], AssistantCache):
            self._assistant_cache = extra["assistant_cache"]

        legacy_config = extra.get("assistant_config") or extra.get("assistant_cache")
        self.assistant_config: Dict[str, Any] = (
            legacy_config if isinstance(legacy_config, dict) else {}
        )

        self._david_client: Any = None
        self.redis = redis or get_redis()
        self.assistant_id = assistant_id
        self.thread_id = thread_id
        self.base_url = base_url or os.getenv("BASE_URL")
        self.api_key = api_key or extra.get("api_key")

        self.model_name = extra.get("model_name", "qwen/Qwen1_5-32B-Chat")
        self.max_context_window = extra.get("max_context_window", 128000)
        self.threshold_percentage = extra.get("threshold_percentage", 0.8)

        self._current_tool_call_id: str | None = None
        self._pending_tool_payload: Optional[Dict[str, Any]] = None
        self._decision_payload: Optional[Dict[str, Any]] = None

        self.setup_services()

        # Ensure Client Access for Mixins
        if hasattr(self, "client"):
            self.project_david_client = self.client

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
        Level 4 Deep Research Stream (Native Persistence Mode).
        Fixes:
        1. Preserves <think>/<plan> tags in DB (Critical for Supervisor/Deep Research memory).
        2. Bypasses _build_tool_structure for DB saving to prevent context loss.
        3. Prevents premature 'completed' status if tool JSON is slightly malformed.
        """

        redis = self.redis
        stream_key = f"stream:{run_id}"
        stop_event = self.start_cancellation_monitor(run_id)

        # 1. State Initialization
        self._current_tool_call_id = None
        self._decision_payload = None
        self._tool_queue = []

        # 'accumulated' will store the raw XML-tagged string (The "Native" format)
        accumulated: str = ""

        # 'assistant_reply' is just the visible text for the user (stripped of tags usually)
        assistant_reply: str = ""

        current_block: str | None = None

        # Flag to detect if model is TRYING to use tools, even if parser fails later
        has_tool_activity: bool = False

        try:
            # 2. Model Mapping
            if hasattr(self, "_get_model_map") and (mapped := self._get_model_map(model)):
                model = mapped

            # 3. Mode Determination & Identity Morphing
            self.assistant_id = assistant_id
            await self._ensure_config_loaded()

            is_deep_research = self.assistant_config.get("deep_research", False)

            LOG.info(f"🧬 [QWEN_WORKER] Starting Stream. Deep Research: {is_deep_research}")

            if is_deep_research:
                from src.api.entities_api.constants.delegator import SUPERVISOR_TOOLS

                assistant_manager = AssistantManager()
                ephemeral_supervisor = await assistant_manager.create_ephemeral_supervisor()
                self.assistant_id = ephemeral_supervisor.id

            # 4. Context Setup
            raw_ctx = await self._set_up_context_window(
                assistant_id=self.assistant_id,
                thread_id=thread_id,
                trunk=True,
                force_refresh=force_refresh,
                agent_mode=getattr(self.assistant_config, "agent_mode", False),
                decision_telemetry=getattr(self.assistant_config, "decision_telemetry", False),
                web_access=getattr(self.assistant_config, "web_access", False),
                deep_research=is_deep_research,
            )

            # Note: For Qwen/DeepSeek, we usually want 'prepare_native_tool_context'
            cleaned_ctx, extracted_tools = self.prepare_native_tool_context(raw_ctx)

            if not api_key:
                yield json.dumps({"type": "error", "content": "Missing API key."})
                return

            yield json.dumps({"type": "status", "status": "started", "run_id": run_id})

            # 5. LLM Turn
            client = self._get_client_instance(api_key=api_key)

            raw_stream = client.stream_chat_completion(
                messages=cleaned_ctx,
                model=model,
                max_tokens=10000,
                temperature=kwargs.get("temperature", 0.6),
                stream=True,
                tools=extracted_tools,
                tool_choice="auto" if kwargs.get("tools") else None,
            )

            async for chunk in DeltaNormalizer.async_iter_deltas(raw_stream, run_id):
                if stop_event.is_set():
                    break

                ctype = chunk.get("type")
                ccontent = chunk.get("content") or ""

                # --- STREAMING LOGIC ---
                # We build 'accumulated' to match exactly what the model output, including tags.

                if ctype == "content":
                    if current_block:
                        accumulated += f"</{current_block}>"
                        current_block = None
                    assistant_reply += ccontent
                    accumulated += ccontent

                elif ctype == "call_arguments":
                    has_tool_activity = True
                    if current_block != "fc":
                        if current_block:
                            accumulated += f"</{current_block}>"
                        accumulated += "<fc>"
                        current_block = "fc"
                    accumulated += ccontent

                elif ctype == "reasoning":
                    if current_block != "think":
                        if current_block:
                            accumulated += f"</{current_block}>"
                        accumulated += "<think>"
                        current_block = "think"
                    # Reasoning goes into accumulated history, but NOT assistant_reply (usually)
                    accumulated += ccontent

                elif ctype == "plan":
                    if current_block != "plan":
                        if current_block:
                            accumulated += f"</{current_block}>"
                        accumulated += "<plan>"
                        current_block = "plan"
                    accumulated += ccontent

                # Emit to Frontend
                # Note: We don't emit raw tool args to frontend here to keep UI clean,
                # but DeltaNormalizer helps handling this upstream usually.
                if ctype == "call_arguments":
                    continue

                yield json.dumps(chunk)
                await self._shunt_to_redis_stream(redis, stream_key, chunk)

            # Close dangling XML tags at end of stream
            if current_block:
                accumulated += f"</{current_block}>"

        except Exception as exc:
            LOG.error(f"Stream Exception: {exc}")
            yield json.dumps({"type": "error", "content": str(exc), "run_id": run_id})
        finally:
            stop_event.set()

        # 6. Post-Turn Processing (Parsing & Persistence)

        # Parse the raw 'accumulated' string to find tools for the Executor
        tool_calls_batch = self.parse_and_set_function_calls(accumulated, assistant_reply)

        # [SAFETY CHECK] If parser failed but we saw activity, try fallback extraction
        if not tool_calls_batch and has_tool_activity:
            LOG.warning("⚠️ Parser missed tools but activity detected. Attempting raw extraction.")
            tool_calls_batch = self.extract_function_calls_within_body_of_text(accumulated)
            if tool_calls_batch:
                self.set_function_call_state(tool_calls_batch)

        # [CRITICAL FIX] NATIVE PERSISTENCE
        # We save 'accumulated' (the raw string with tags).
        # We DO NOT use _build_tool_structure(tool_calls_batch) for the save,
        # because that would strip the <think> and <plan> tags.
        message_to_save = accumulated

        final_status = StatusEnum.completed.value

        if tool_calls_batch:
            # We populate the queue for the Orchestrator to read
            self._tool_queue = tool_calls_batch
            final_status = StatusEnum.pending_action.value

            yield json.dumps({"type": "status", "status": "processing", "run_id": run_id})

        # Persist the RAW TURN to the Database
        if message_to_save:
            await self.finalize_conversation(message_to_save, thread_id, self.assistant_id, run_id)

        # Update Run status (Pending Action or Completed)
        if self.project_david_client:
            await asyncio.to_thread(
                self.project_david_client.runs.update_run_status, run_id, final_status
            )

        if not tool_calls_batch:
            yield json.dumps({"type": "status", "status": "complete", "run_id": run_id})

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
