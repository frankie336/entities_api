from __future__ import annotations

import asyncio
import json
import os
import uuid
import re
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

from dotenv import load_dotenv
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from entities_api.cache import assistant_cache
from entities_api.cache.assistant_cache import AssistantCache
from entities_api.clients.delta_normalizer import DeltaNormalizer
from src.api.entities_api.dependencies import get_redis, get_redis_sync
from src.api.entities_api.orchestration.engine.orchestrator_core import OrchestratorCore
from src.api.entities_api.orchestration.mixins.provider_mixins import _ProviderMixins

load_dotenv()
LOG = LoggingUtility()


class GptOssBaseWorker(
    _ProviderMixins,
    OrchestratorCore,
    ABC,
):
    """
    Async Base for GPT-OSS Providers.
    Level 3 Refactor: Supports tool batching, planning deltas, and
    automated multi-turn self-correction.
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
        # assistant_cache: dict | None = None,
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

        # 1. IMMEDIATE ATTRIBUTE SETTING (Required for Service Registry)
        self.model_name = extra.get("model_name") or extra.get("model") or "openai/gpt-oss-120b"
        self.max_context_window = extra.get("max_context_window", 131072)
        self.threshold_percentage = extra.get("threshold_percentage", 0.8)

        # 2. Setup Identifiers & Clients
        self.assistant_id = assistant_id
        self.thread_id = thread_id
        self.base_url = base_url or os.getenv("BASE_URL")
        self.api_key = api_key
        self.redis = redis or get_redis()
        self._david_client: Any = None
        # self._assistant_cache: dict = assistant_cache or extra.get("assistant_cache") or {}

        # 3. Standardized L3 Tracking Variables
        self._current_tool_call_id: str | None = None
        self._pending_tool_payload: Optional[Dict[str, Any]] = None
        self._decision_payload: Optional[Dict[str, Any]] = None
        self._tool_queue: List[Dict] = []

        # 4. Initialize Services (Now safe because model_name is set)
        self.setup_services()

        # 5. ToolRoutingMixin Safety Check
        if not hasattr(self, "get_function_call_state"):
            LOG.error("CRITICAL: ToolRoutingMixin failed to load.")
            self.get_function_call_state = lambda: []
            self.set_function_call_state = lambda x: None
            self.set_tool_response_state = lambda x: None

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
        stream_reasoning: bool = True,  # Default to True for L3
        api_key: str | None = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """
        Level 3 Agentic Stream:
        Orchestrates real-time plan visualization and batch tool dispatch.
        """
        import uuid

        redis = self.redis
        stream_key = f"stream:{run_id}"
        stop_event = self.start_cancellation_monitor(run_id)

        # Reset Turn State
        self._current_tool_call_id = None
        self._decision_payload = None
        self._tool_queue = []

        accumulated: str = ""
        assistant_reply: str = ""
        reasoning_reply: str = ""
        decision_buffer: str = ""
        plan_buffer: str = ""
        current_block: str | None = None

        try:
            if hasattr(self, "_get_model_map") and (mapped := self._get_model_map(model)):
                model = mapped

            # Ensure config is hot to resolve L3 flags
            self.assistant_id = assistant_id
            await self._ensure_config_loaded()
            agent_mode = self.assistant_config.get("agent_mode", False)
            decision_telemetry = self.assistant_config.get("decision_telemetry", True)

            LOG.debug(f"Agent Mode -> Agent: {agent_mode}, Telemetry: {decision_telemetry}")

            # Context Setup
            raw_ctx = await self._set_up_context_window(
                assistant_id=assistant_id,
                thread_id=thread_id,
                trunk=True,
                structured_tool_call=True,
                force_refresh=force_refresh,
                agent_mode=agent_mode,
                decision_telemetry=decision_telemetry,
            )
            cleaned_ctx, extracted_tools = self.prepare_native_tool_context(raw_ctx)

            if not api_key:
                yield json.dumps({"type": "error", "content": "Missing API key."})
                return

            client = self._get_client_instance(api_key=api_key)

            # [DEBUG LOG]
            LOG.info(
                f"\nRAW_CTX_DUMP (Agent: {agent_mode}):\n{json.dumps(cleaned_ctx, indent=2, ensure_ascii=False)}"
            )

            raw_stream = client.stream_chat_completion(
                messages=cleaned_ctx,
                model=model,
                tools=None if stream_reasoning else extracted_tools,
                temperature=kwargs.get("temperature", 0.6),
                **kwargs,
            )

            yield json.dumps({"type": "status", "status": "started", "run_id": run_id})

            async for chunk in DeltaNormalizer.async_iter_deltas(raw_stream, run_id):
                if stop_event.is_set():
                    break

                ctype = chunk.get("type")
                ccontent = chunk.get("content") or ""

                # --- REAL-TIME L3 STATE MACHINE ---
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
                elif ctype in ("tool_name", "call_arguments"):
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

                if ctype in ("tool_name", "call_arguments"):
                    continue
                yield json.dumps(chunk)
                await self._shunt_to_redis_stream(redis, stream_key, chunk)

            if current_block == "fc":
                accumulated += "</fc>"
            elif current_block == "think":
                accumulated += "</think>"
            elif current_block == "plan":
                accumulated += "</plan>"

        except Exception as exc:
            LOG.error(f"DEBUG: Stream Exception: {exc}")
            err = {"type": "error", "content": f"GPT-OSS L3 stream error: {exc}", "run_id": run_id}
            yield json.dumps(err)
            await self._shunt_to_redis_stream(redis, stream_key, err)
        finally:
            stop_event.set()

        if decision_buffer:
            try:
                self._decision_payload = json.loads(decision_buffer.strip())
            except Exception:
                pass

        yield json.dumps({"type": "status", "status": "processing", "run_id": run_id})

        # --- [LEVEL 3] PARSE BATCH & SYNC IDs ---
        tool_calls_batch = self.parse_and_set_function_calls(accumulated, assistant_reply)
        message_to_save = assistant_reply
        final_status = StatusEnum.completed.value

        if tool_calls_batch:
            self._tool_queue = tool_calls_batch
            final_status = StatusEnum.pending_action.value

            # Build formal tool call array for Turn 2 context consistency
            tool_calls_structure = []
            for tool in tool_calls_batch:
                tool_id = tool.get("id") or f"call_{uuid.uuid4().hex[:8]}"
                tool_calls_structure.append(
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

            # Persist batch as structured JSON list
            message_to_save = json.dumps(tool_calls_structure)
            LOG.info(f"🚀 [GPT-OSS Batch] Turn 1: {len(tool_calls_structure)} tools dispatched.")

        # Finalize and update status
        if message_to_save:
            await self.finalize_conversation(message_to_save, thread_id, assistant_id, run_id)

        if self.project_david_client:
            await asyncio.to_thread(
                self.project_david_client.runs.update_run_status, run_id, final_status
            )

        if not tool_calls_batch:
            yield json.dumps({"type": "status", "status": "complete", "run_id": run_id})
