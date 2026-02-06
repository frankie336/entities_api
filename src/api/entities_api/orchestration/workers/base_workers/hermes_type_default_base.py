from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, List, Optional

from dotenv import load_dotenv
from projectdavid_common.utilities.logging_service import LoggingUtility

from entities_api.cache import assistant_cache
from entities_api.cache.assistant_cache import AssistantCache
from entities_api.clients.delta_normalizer import DeltaNormalizer
# --- DEPENDENCIES ---
from src.api.entities_api.dependencies import get_redis, get_redis_sync
from src.api.entities_api.orchestration.engine.orchestrator_core import \
    OrchestratorCore
# --- MIXINS ---
from src.api.entities_api.orchestration.mixins.provider_mixins import \
    _ProviderMixins

load_dotenv()
LOG = LoggingUtility()


class HermesDefaultBaseWorker(
    _ProviderMixins,
    OrchestratorCore,
    ABC,
):
    """
    Async Base for 'deepcogito/cogito-v2-preview-llama-405B' (Hermes Type).
    Migrated to Async-First Architecture.
    """

    def __init__(
        self,
        *,
        assistant_id: str | None = None,
        thread_id: str | None = None,
        redis=None,
        base_url: str | None = None,
        api_key: str | None = None,
        # assistant_cache: dict | None = None, # Note: This arg shadows the module import
        assistant_cache_service: Optional[AssistantCache] = None,
        **extra,
    ) -> None:

        # 1. Capture the 'assistant_cache' argument manually from locals or extra
        # We do this to avoid confusion with the imported module 'assistant_cache'
        arg_assistant_cache_dict = extra.get("assistant_cache")

        # 2. Setup Redis
        self.redis = redis or get_redis_sync()

        # 3. Setup the Cache Service (The "New Way")
        # Initialize defaults
        self._assistant_cache: AssistantCache | None = None

        if assistant_cache_service:
            self._assistant_cache = assistant_cache_service
        elif "assistant_cache" in extra and isinstance(
            extra["assistant_cache"], AssistantCache
        ):
            self._assistant_cache = extra["assistant_cache"]

        # 4. Setup the Data/Config (The "Old Way" renamed)
        # Consolidate dictionary configs into self.assistant_config
        legacy_config = extra.get("assistant_config") or arg_assistant_cache_dict

        self.assistant_config: Dict[str, Any] = (
            legacy_config if isinstance(legacy_config, dict) else {}
        )

        self._david_client: Any = None

        self.redis = redis or get_redis()
        self.assistant_id = assistant_id
        self.thread_id = thread_id
        self.base_url = base_url or os.getenv("BASE_URL")
        self.api_key = api_key or extra.get("api_key")

        self.model_name = extra.get(
            "model_name", "deepcogito/cogito-v2-preview-llama-405B"
        )
        self.max_context_window = extra.get("max_context_window", 128000)
        self.threshold_percentage = extra.get("threshold_percentage", 0.8)

        # Standardized tracking variables
        self._current_tool_call_id: str | None = None
        self._pending_tool_payload: Optional[Dict[str, Any]] = None
        self._decision_payload: Optional[Dict[str, Any]] = None

        self.setup_services()

        # Safety stubbing (Standardized from GptOss)
        if not hasattr(self, "get_function_call_state"):
            LOG.error("CRITICAL: ToolRoutingMixin failed to load.")
            self.get_function_call_state = lambda: None
            self.set_function_call_state = lambda x: None
            self.set_tool_response_state = lambda x: None

        LOG.debug("DeepCogito worker initialized (assistant=%s)", assistant_id)

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
    ) -> AsyncGenerator[str, None]:
        """
        Level 3 Agentic Stream with ID-Parity:
        - Orchestrates Plan vs Action cycles.
        - Injects Hermes-style tool envelopes for multi-manifest turns.
        - Ensures consistency between Dialogue ID and Control ID.
        """
        import asyncio
        import uuid

        from projectdavid_common.validation import StatusEnum

        redis = self.redis
        stream_key = f"stream:{run_id}"
        stop_event = self.start_cancellation_monitor(run_id)

        # Early Variable Initialization
        self._current_tool_call_id = None
        self._decision_payload = None
        self._tool_queue: List[Dict] = []

        accumulated: str = ""
        assistant_reply: str = ""
        reasoning_reply: str = ""
        decision_buffer: str = ""
        plan_buffer: str = ""
        current_block: str | None = None

        try:
            if hasattr(self, "_get_model_map") and (
                mapped := self._get_model_map(model)
            ):
                model = mapped

            self.assistant_id = assistant_id
            # [NEW] Ensure cache is hot before starting
            await self._ensure_config_loaded()
            agent_mode_setting = self.assistant_config.get("agent_mode", False)
            decision_telemetry = self.assistant_config.get("decision_telemetry", True)

            ctx = await self._set_up_context_window(
                assistant_id,
                thread_id,
                trunk=True,
                force_refresh=force_refresh,
                agent_mode=agent_mode_setting,
                decision_telemetry=decision_telemetry,
            )

            if not api_key:
                yield json.dumps({"type": "error", "content": "Missing API key."})
                return

            yield json.dumps({"type": "status", "status": "started", "run_id": run_id})

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
            err = {"type": "error", "content": f"Stream error: {exc}", "run_id": run_id}
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
        # The parser ensures every tool in the list has a 'id' key.
        tool_calls_batch = self.parse_and_set_function_calls(
            accumulated, assistant_reply
        )

        message_to_save = assistant_reply
        final_status = StatusEnum.completed.value

        if tool_calls_batch:
            # 1. Update the internal queue for the dispatcher (process_tool_calls)
            self._tool_queue = tool_calls_batch
            final_status = StatusEnum.pending_action.value

            # 2. Build the Hermes/OpenAI Structured Envelope for the Dialogue
            # This is what makes Turn 2 contextually consistent.
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

            # CRITICAL: We overwrite message_to_save with the standard tool structure
            message_to_save = json.dumps(tool_calls_structure)

            # [LOGGING] Verify ID Parity
            LOG.info(
                f"\n🚀 [L3 AGENT MANIFEST] Turn 1 Batch of {len(tool_calls_structure)}"
            )
            for item in tool_calls_structure:
                LOG.info(f"   ▸ Tool: {item['function']['name']} | ID: {item['id']}")

        # Persistence: Assistant Plan/Actions saved to Thread
        if message_to_save:
            await self.finalize_conversation(
                message_to_save, thread_id, assistant_id, run_id
            )

        # Update Run status to trigger Dispatch Turn
        if self.project_david_client:
            await asyncio.to_thread(
                self.project_david_client.runs.update_run_status, run_id, final_status
            )

        if not tool_calls_batch:
            yield json.dumps({"type": "status", "status": "complete", "run_id": run_id})
