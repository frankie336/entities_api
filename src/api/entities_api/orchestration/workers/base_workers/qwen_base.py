# src/api/entities_api/workers/qwen_worker.py
from __future__ import annotations

import asyncio
import json
import os
import uuid
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

from dotenv import load_dotenv
from projectdavid import StatusEvent, StreamEvent
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from entities_api.cache.assistant_cache import AssistantCache
from entities_api.clients.delta_normalizer import DeltaNormalizer
# --- DEFINITIONS FOR HOT-SWAPPING ---
from src.api.entities_api.constants.delegator import SUPERVISOR_TOOLS
# --- DEPENDENCIES ---
from src.api.entities_api.dependencies import get_redis, get_redis_sync
from src.api.entities_api.orchestration.engine.orchestrator_core import \
    OrchestratorCore
from src.api.entities_api.orchestration.instructions.definitions import \
    SUPERVISOR_SYSTEM_PROMPT
from src.api.entities_api.orchestration.mixins.delegation_mixin import \
    DelegationMixin
# --- MIXINS ---
from src.api.entities_api.orchestration.mixins.provider_mixins import \
    _ProviderMixins
from src.api.entities_api.orchestration.mixins.scratchpad_mixin import \
    ScratchpadMixin

load_dotenv()
LOG = LoggingUtility()

# Tools that trigger a Re-Entrant Loop (The Supervisor Logic)
INTERNAL_TOOLS = {
    "delegate_research_task",
    "read_scratchpad",
    "update_scratchpad",
    "append_scratchpad",
}


class QwenBaseWorker(
    _ProviderMixins,
    OrchestratorCore,
    DelegationMixin,
    ScratchpadMixin,
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
        Level 3 Agentic Stream with ID-Parity AND Level 4 Deep Research Loops.
        """
        redis = self.redis
        stream_key = f"stream:{run_id}"
        stop_event = self.start_cancellation_monitor(run_id)

        self._current_tool_call_id = None
        self._decision_payload = None
        self._tool_queue: List[Dict] = []

        # --- [1] DETERMINE MODE ---
        is_deep_research = self.assistant_config.get("deep_research_enabled", False)

        # FIX 1: Enforce valid Together AI Model
        # If the run was created with 'gpt-4', map it to Qwen to prevent 400 Errors.
        if model in ["gpt-4", "gpt-3.5-turbo"]:
            model = "Qwen/Qwen2.5-72B-Instruct-Turbo"
        elif hasattr(self, "_get_model_map") and (mapped := self._get_model_map(model)):
            model = mapped

        max_loops = 30 if is_deep_research else 1
        current_loop_index = 0

        # Define active tools for this session
        active_tools = kwargs.get("tools", None)

        try:
            self.assistant_id = assistant_id
            await self._ensure_config_loaded()

            # --- [2] SETUP CONTEXT (MAIN ASSISTANT) ---
            ctx = await self._set_up_context_window(
                assistant_id,
                thread_id,
                trunk=True,
                force_refresh=force_refresh,
                agent_mode=self.assistant_config.get("agent_mode", False),
                decision_telemetry=self.assistant_config.get(
                    "decision_telemetry", True
                ),
                web_access=self.assistant_config.get("web_access", False),
            )

            # --- [3] EPHEMERAL SUPERVISOR INJECTION ---
            if is_deep_research:
                LOG.info(
                    f"🧬 [MORPH] Run {run_id}: Swapping Main Persona for Deep Research Supervisor."
                )

                # A. Hot-Swap System Prompt
                if ctx and ctx[0].get("role") == "system":
                    ctx[0]["content"] = SUPERVISOR_SYSTEM_PROMPT
                else:
                    ctx.insert(
                        0, {"role": "system", "content": SUPERVISOR_SYSTEM_PROMPT}
                    )

                # B. Force Supervisor Tools
                active_tools = SUPERVISOR_TOOLS

            if not api_key:
                yield json.dumps({"type": "error", "content": "Missing API key."})
                return

            yield json.dumps(
                {
                    "type": "status",
                    "status": "started",
                    "state": "started",
                    "run_id": run_id,
                }
            )
            client = self._get_client_instance(api_key=api_key)

            # --- [4] THE LOOP ---
            while current_loop_index < max_loops:
                current_loop_index += 1
                if stop_event.is_set():
                    break

                accumulated: str = ""
                assistant_reply: str = ""
                reasoning_reply: str = ""
                decision_buffer: str = ""
                plan_buffer: str = ""
                current_block: str | None = None

                # Call LLM
                try:
                    # FIX 2: Reduce max_tokens to 4096 (Safe limit for Together AI)
                    raw_stream = client.stream_chat_completion(
                        messages=ctx,
                        model=model,
                        max_tokens=4096,  # <--- CHANGED FROM 10000
                        temperature=kwargs.get("temperature", 0.6),
                        stream=True,
                        tools=active_tools,
                        tool_choice="auto" if active_tools else None,
                    )

                    async for chunk in DeltaNormalizer.async_iter_deltas(
                        raw_stream, run_id
                    ):
                        if stop_event.is_set():
                            break

                        ctype = chunk.get("type")
                        ccontent = chunk.get("content") or ""

                        # --- BLOCK PARSING (Qwen/Deepseek Style) ---
                        if ctype == "content":
                            if current_block == "fc":
                                accumulated += "</fc>"
                            elif current_block == "think":
                                accumulated += "</think>"
                            elif current_block == "plan":
                                accumulated += "</plan>"
                            current_block = None
                            assistant_reply += ccontent
                            accumulated += ccontent
                        elif ctype == "call_arguments":
                            if current_block != "fc":
                                if current_block == "think":
                                    accumulated += "</think>"
                                elif current_block == "plan":
                                    accumulated += "</plan>"
                                accumulated += "<fc>"
                                current_block = "fc"
                            accumulated += ccontent
                        elif ctype == "reasoning":
                            if current_block != "think":
                                if current_block == "fc":
                                    accumulated += "</fc>"
                                elif current_block == "plan":
                                    accumulated += "</plan>"
                                accumulated += "<think>"
                                current_block = "think"
                            reasoning_reply += ccontent
                        elif ctype == "plan":
                            if current_block != "plan":
                                if current_block == "fc":
                                    accumulated += "</fc>"
                                elif current_block == "think":
                                    accumulated += "</think>"
                                accumulated += "<plan>"
                                current_block = "plan"
                            plan_buffer += ccontent
                            accumulated += ccontent
                        elif ctype == "decision":
                            decision_buffer += ccontent
                            if current_block == "fc":
                                accumulated += "</fc>"
                            elif current_block == "think":
                                accumulated += "</think>"
                            elif current_block == "plan":
                                accumulated += "</plan>"
                            current_block = "decision"

                        if ctype == "call_arguments":
                            continue

                        # Yield to Frontend
                        yield json.dumps(chunk)
                        await self._shunt_to_redis_stream(redis, stream_key, chunk)

                except Exception as e:
                    LOG.error(f"Supervisor LLM Error: {e}")
                    yield json.dumps(
                        {"type": "error", "content": f"Supervisor LLM Error: {e}"}
                    )
                    break

                # ... (Rest of parsing logic remains same) ...

                # Close blocks
                if current_block == "fc":
                    accumulated += "</fc>"
                elif current_block == "think":
                    accumulated += "</think>"
                elif current_block == "plan":
                    accumulated += "</plan>"

                if decision_buffer:
                    try:
                        self._decision_payload = json.loads(decision_buffer.strip())
                    except Exception:
                        pass

                # Parse Tools
                tool_calls_batch = self.parse_and_set_function_calls(
                    accumulated, assistant_reply
                )

                # --- [5] BRANCHING LOGIC ---
                if not tool_calls_batch:
                    break  # Done

                # Check if Supervisor Tools are being used
                is_internal_batch = is_deep_research and all(
                    t["name"] in INTERNAL_TOOLS for t in tool_calls_batch
                )

                if is_internal_batch:
                    # 1. Update History (Assistant Turn)
                    tool_calls_structure = self._build_tool_structure(tool_calls_batch)
                    ctx.append(
                        {
                            "role": "assistant",
                            "content": assistant_reply or None,
                            "tool_calls": tool_calls_structure,
                        }
                    )

                    # 2. Execute Inline (The Supervisor Actions)
                    for tool, struct in zip(tool_calls_batch, tool_calls_structure):
                        t_name = tool["name"]
                        t_args = tool.get("arguments", {})
                        t_id = struct["id"]

                        yield json.dumps(
                            {
                                "type": "status",
                                "status": "processing",
                                "state": "in_progress",
                                "content": f"Supervisor: {t_name}...",
                            }
                        )

                        output_result = "Action Completed."

                        # --- EXECUTION ---
                        try:
                            if t_name == "delegate_research_task":
                                # EPHEMERAL WORKER SPAWNS HERE
                                res_list = []
                                async for event in self._run_worker_loop_generator(
                                    t_args.get("task"),
                                    t_args.get("requirements", ""),
                                    run_id,
                                    res_list,
                                ):
                                    if isinstance(event, StatusEvent):
                                        evt_state = getattr(
                                            event, "state", "in_progress"
                                        )
                                        yield json.dumps(
                                            {
                                                "type": "status",
                                                "status": "processing",
                                                "state": evt_state,
                                                "content": f"Worker: {event.message}",
                                            }
                                        )
                                output_result = (
                                    res_list[0] if res_list else "No worker output."
                                )

                            elif t_name == "read_scratchpad":
                                output_result = await asyncio.to_thread(
                                    self.project_david_client.tools.scratchpad_read,
                                    thread_id=thread_id,
                                )
                            elif t_name == "update_scratchpad":
                                output_result = await asyncio.to_thread(
                                    self.project_david_client.tools.scratchpad_update,
                                    thread_id=thread_id,
                                    content=t_args.get("content"),
                                )
                            elif t_name == "append_scratchpad":
                                output_result = await asyncio.to_thread(
                                    self.project_david_client.tools.scratchpad_append,
                                    thread_id=thread_id,
                                    note=t_args.get("note"),
                                )
                        except Exception as e:
                            output_result = f"Error: {e}"

                        # 3. Update History (Tool Result)
                        ctx.append(
                            {
                                "role": "tool",
                                "tool_call_id": t_id,
                                "name": t_name,
                                "content": str(output_result),
                            }
                        )

                    continue  # Loop back to Supervisor

                else:
                    break  # External tool or finish

        except Exception as exc:
            LOG.error(f"DEBUG: Stream Exception: {exc}")
            err = {"type": "error", "content": f"Stream error: {exc}", "run_id": run_id}
            yield json.dumps(err)
            await self._shunt_to_redis_stream(redis, stream_key, err)
        finally:
            stop_event.set()

        yield json.dumps(
            {
                "type": "status",
                "status": "processing",
                "state": "processing",
                "run_id": run_id,
            }
        )

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
