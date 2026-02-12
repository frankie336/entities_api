# src/api/entities_api/workers/qwen_worker.py
from __future__ import annotations

import asyncio
import json
import os
import uuid
from abc import abstractmethod
from typing import Any, AsyncGenerator, Dict, Optional, Union

from dotenv import load_dotenv
from projectdavid import StreamEvent
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from entities_api.cache.assistant_cache import AssistantCache
from entities_api.clients.delta_normalizer import DeltaNormalizer
from entities_api.constants.assistant import PLATFORM_TOOLS
# --- DEPENDENCIES ---
from src.api.entities_api.dependencies import get_redis, get_redis_sync
from src.api.entities_api.orchestration.engine.orchestrator_core import \
    OrchestratorCore
# --- MIXINS ---
from src.api.entities_api.orchestration.mixins.provider_mixins import \
    _ProviderMixins

load_dotenv()
LOG = LoggingUtility()


class DeepResearchBaseWorker(
    _ProviderMixins,
    OrchestratorCore,
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

        super().__init__(**extra)  # <--- THIS IS MISSING

        self.api_key = api_key  # <-- need a solution to dynamically send this

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

            # await self._ensure_config_loaded()

            # 4. Context Setup
            ctx = await self._set_up_context_window(
                assistant_id=self.assistant_id,
                thread_id=thread_id,
                trunk=True,
                force_refresh=force_refresh,
                agent_mode=False,
                decision_telemetry=False,
                web_access=False,
                deep_research=False,
                research_worker=True,
            )

            if not api_key:
                yield json.dumps({"type": "error", "content": "Missing API key."})
                return

            yield json.dumps({"type": "status", "status": "started", "run_id": run_id})

            # 5. LLM Turn (Single Lifecycle)

            client = self._get_client_instance(api_key=api_key)

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
                LOG.error(
                    f"ORCHESTRATOR ▸ Turn {turn_count} stream failed: {stream_exc}"
                )
                # Return a proper error event if possible, otherwise JSON string
                yield json.dumps(
                    {"type": "error", "content": f"Stream failure: {stream_exc}"}
                )
                break

            # --- 3. BATCH EVALUATION ---
            batch = self.get_function_call_state()

            if not batch:
                LOG.info(f"ORCHESTRATOR ▸ Turn {turn_count} completed with text.")
                break

            has_consumer_tool = any(
                tool.get("name") not in PLATFORM_TOOLS for tool in batch
            )

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
                LOG.info(
                    f"ORCHESTRATOR ▸ Platform batch {turn_count} complete. Stabilizing..."
                )
                await asyncio.sleep(0.5)
                current_message_id = None
                continue
            else:
                LOG.info(
                    f"ORCHESTRATOR ▸ Consumer tool detected in batch. Handing over to SDK."
                )
                return

        if turn_count >= max_turns:
            LOG.error(f"ORCHESTRATOR ▸ Max turns reached.")
