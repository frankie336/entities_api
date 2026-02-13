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
from src.api.entities_api.orchestration.engine.orchestrator_core import \
    OrchestratorCore
# --- MIXINS ---
from src.api.entities_api.orchestration.mixins.provider_mixins import \
    _ProviderMixins
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
        elif "assistant_cache" in extra and isinstance(
            extra["assistant_cache"], AssistantCache
        ):
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
        Level 4 Deep Research Stream (Flat Logic).
        Swaps identity if in deep_research mode, then processes a single turn.
        Recursion is handled by the outer process_conversation loop.
        """

        redis = self.redis
        stream_key = f"stream:{run_id}"
        stop_event = self.start_cancellation_monitor(run_id)

        # 1. State Initialization
        self._current_tool_call_id = None
        self._decision_payload = None
        self._tool_queue = []

        accumulated: str = ""
        assistant_reply: str = ""
        current_block: str | None = None

        try:
            # 2. Model Mapping
            if hasattr(self, "_get_model_map") and (
                mapped := self._get_model_map(model)
            ):
                model = mapped

            # 3. Mode Determination & Identity Morphing
            self.assistant_id = assistant_id
            await self._ensure_config_loaded()

            is_deep_research = self.assistant_config.get("deep_research", False)

            LOG.info("[DEEP_RESEARCH_MODE]=%s", is_deep_research)

            active_tools = kwargs.get("tools", None)

            LOG.critical("██████ [DEEP_RESEARCH_MODE]=%s ██████", is_deep_research)
            print(
                f"\n\n########## DEEP_RESEARCH_MODE={is_deep_research} ##########\n\n"
            )

            if is_deep_research:
                from src.api.entities_api.constants.delegator import \
                    SUPERVISOR_TOOLS

                LOG.info(
                    f"🧬 [MORPH] Run {run_id}: Swapping to Supervisor via Service Layer."
                )

                # -------------------------------------------------------
                # Create supervisor assistant here
                #
                # ----------------------------------------------------------
                assistant_manager = AssistantManager()
                ephemeral_supervisor = (
                    await assistant_manager.create_ephemeral_supervisor()
                )
                self.assistant_id = ephemeral_supervisor.id

            # 4. Context Setup
            raw_ctx = await self._set_up_context_window(
                assistant_id=self.assistant_id,
                thread_id=thread_id,
                trunk=True,
                force_refresh=force_refresh,
                agent_mode=getattr(self.assistant_config, "agent_mode", False),
                decision_telemetry=getattr(
                    self.assistant_config, "decision_telemetry", False
                ),
                web_access=getattr(self.assistant_config, "web_access", False),
                deep_research=is_deep_research,
            )
            cleaned_ctx, extracted_tools = self.prepare_native_tool_context(raw_ctx)

            if not api_key:
                yield json.dumps({"type": "error", "content": "Missing API key."})
                return

            yield json.dumps({"type": "status", "status": "started", "run_id": run_id})

            # 5. LLM Turn (Single Lifecycle)
            client = self._get_client_instance(api_key=api_key)

            raw_stream = client.stream_chat_completion(
                messages=cleaned_ctx,
                model=model,
                max_tokens=10000,
                temperature=kwargs.get("temperature", 0.6),
                stream=True,
                tools=extracted_tools,
                tool_choice="auto" if active_tools else None,
            )

            async for chunk in DeltaNormalizer.async_iter_deltas(raw_stream, run_id):
                if stop_event.is_set():
                    break

                ctype = chunk.get("type")
                ccontent = chunk.get("content") or ""

                if ctype == "content":
                    if current_block in ["fc", "think", "plan"]:
                        accumulated += f"</{current_block}>"
                    current_block = None
                    assistant_reply += ccontent
                    accumulated += ccontent
                elif ctype == "call_arguments":
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
                elif ctype == "plan":
                    if current_block != "plan":
                        if current_block:
                            accumulated += f"</{current_block}>"
                        accumulated += "<plan>"
                        current_block = "plan"
                    accumulated += ccontent

                if ctype == "call_arguments":
                    continue

                yield json.dumps(chunk)
                await self._shunt_to_redis_stream(redis, stream_key, chunk)

            # Close dangling XML tags
            if current_block:
                accumulated += f"</{current_block}>"

        except Exception as exc:
            LOG.error(f"Stream Exception: {exc}")
            yield json.dumps({"type": "error", "content": str(exc), "run_id": run_id})
        finally:
            stop_event.set()

        # 6. Post-Turn Processing (Parsing & Persistence)
        tool_calls_batch = self.parse_and_set_function_calls(
            accumulated, assistant_reply
        )

        message_to_save = assistant_reply
        final_status = StatusEnum.completed.value

        if tool_calls_batch:
            # Prepare internal queue for the Tool Router
            self._tool_queue = tool_calls_batch
            final_status = StatusEnum.pending_action.value

            # Build Hermes/OpenAI envelope for Turn 2 parity
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

            # Use structure as the message content to ensure context hygiene
            message_to_save = json.dumps(tool_calls_structure)
            yield json.dumps(
                {"type": "status", "status": "processing", "run_id": run_id}
            )

        # Persist turn to DB Thread
        if message_to_save:
            await self.finalize_conversation(
                message_to_save, thread_id, self.assistant_id, run_id
            )

        # Update Run state to allow consumer to trigger tool execution
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
