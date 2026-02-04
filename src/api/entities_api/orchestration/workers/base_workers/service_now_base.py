from __future__ import annotations

import asyncio
import json
import os
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, Optional

from dotenv import load_dotenv
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from entities_api.clients.delta_normalizer import DeltaNormalizer
# --- DEPENDENCIES ---
from src.api.entities_api.dependencies import get_redis
from src.api.entities_api.orchestration.engine.orchestrator_core import \
    OrchestratorCore
# --- MIXINS ---
from src.api.entities_api.orchestration.mixins.provider_mixins import \
    _ProviderMixins

load_dotenv()
LOG = LoggingUtility()


class ServiceNowBaseWorker(
    _ProviderMixins,
    OrchestratorCore,
    ABC,
):
    """
    Async Base for ServiceNow Providers (Apriel-1.6-15b-Thinker).
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
        assistant_cache: dict | None = None,
        **extra,
    ) -> None:
        self._david_client: Any = None
        self._assistant_cache: dict = (
            assistant_cache or extra.get("assistant_cache") or {}
        )
        self.redis = redis or get_redis()
        self.assistant_id = assistant_id
        self.thread_id = thread_id
        self.base_url = base_url or os.getenv("BASE_URL")
        self.api_key = api_key or extra.get("api_key")

        self.model_name = extra.get(
            "model_name", "ServiceNow-AI/Apriel-1.6-15b-Thinker"
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

        LOG.debug(f"{self.__class__.__name__} ready (assistant={assistant_id})")

    @abstractmethod
    def _get_client_instance(self, api_key: str):
        pass

    @property
    def assistant_cache(self) -> dict:
        return self._assistant_cache

    @assistant_cache.setter
    def assistant_cache(self, value: dict) -> None:
        self._assistant_cache = value

    async def stream(
        self,
        thread_id: str,
        message_id: str | None,
        run_id: str,
        assistant_id: str,
        model: Any,
        *,
        force_refresh: bool = False,
        stream_reasoning: bool = False,
        api_key: str | None = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        redis = self.redis
        stream_key = f"stream:{run_id}"
        stop_event = self.start_cancellation_monitor(run_id)

        # --- SYNC-REPLICA 1: Early Variable Initialization ---
        self._current_tool_call_id = None
        self._pending_tool_payload = None
        self._decision_payload = None

        assistant_reply, accumulated, reasoning_reply, decision_buffer = "", "", "", ""
        current_block = None

        try:
            if hasattr(self, "_get_model_map") and (
                mapped := self._get_model_map(model)
            ):
                model = mapped

            # Async Context Setup
            ctx = await self._set_up_context_window(
                assistant_id,
                thread_id,
                trunk=True,
                force_refresh=force_refresh,
            )

            if not api_key:
                yield json.dumps({"type": "error", "content": "Missing API key."})
                return

            yield json.dumps({"type": "status", "status": "started", "run_id": run_id})

            # -----------------------------------------------------------
            # STANDARDIZED CLIENT EXECUTION (GPT-OSS Style)
            # -----------------------------------------------------------
            client = self._get_client_instance(api_key=api_key)
            # ServiceNow relies on prompt injection for tools, passing raw messages.
            raw_stream = client.stream_chat_completion(
                messages=ctx,
                model=model,
                max_tokens=10000,
                temperature=kwargs.get("temperature", 0.6),
                stream=True,
            )
            # -----------------------------------------------------------

            async for chunk in DeltaNormalizer.async_iter_deltas(raw_stream, run_id):
                if stop_event.is_set():
                    break

                ctype = chunk.get("type")
                ccontent = chunk.get("content") or ""

                # --- SERVICENOW SPECIFIC PARSING LOGIC ---
                if ctype == "content":
                    if current_block == "fc":
                        accumulated += "</fc>"
                    elif current_block == "think":
                        accumulated += "</think>"
                    current_block = None
                    assistant_reply += ccontent

                elif ctype == "call_arguments":
                    if current_block != "fc":
                        if current_block == "think":
                            accumulated += "</think>"
                        accumulated += "<fc>"
                        current_block = "fc"

                elif ctype == "reasoning":
                    if current_block != "think":
                        if current_block == "fc":
                            accumulated += "</fc>"
                        accumulated += "<think>"
                        current_block = "think"
                    reasoning_reply += ccontent

                # Check for decision payload (if supported by this model later)
                elif ctype == "decision":
                    decision_buffer += ccontent

                # Accumulate raw stream for persistence (Logic from original worker)
                accumulated += ccontent

                # Filter: ServiceNow blocks yielding tool artifacts
                if ctype not in ("tool_name", "call_arguments"):
                    yield json.dumps(chunk)

                await self._shunt_to_redis_stream(redis, stream_key, chunk)

            if current_block == "fc":
                accumulated += "</fc>"
            elif current_block == "think":
                accumulated += "</think>"

        except Exception as exc:
            LOG.error(f"DEBUG: Stream Exception: {exc}")
            err = {
                "type": "error",
                "content": f"ServiceNow stream error: {exc}",
                "run_id": run_id,
            }
            yield json.dumps(err)
            await self._shunt_to_redis_stream(redis, stream_key, err)
        finally:
            stop_event.set()

        yield json.dumps({"type": "status", "status": "complete", "run_id": run_id})

        # --- SYNC-REPLICA 2: Validate Decision Payload (Standardized) ---
        if decision_buffer:
            try:
                self._decision_payload = json.loads(decision_buffer.strip())
                LOG.info(f"Decision payload validated: {self._decision_payload}")
            except Exception as e:
                LOG.error(f"Failed to parse decision payload: {e}")

        # Keep-Alive Heartbeat
        yield json.dumps({"type": "status", "status": "processing", "run_id": run_id})

        # --- SYNC-REPLICA 3: Persistence & Detection ---
        has_fc = self.parse_and_set_function_calls(accumulated, assistant_reply)
        message_to_save = assistant_reply
        final_status = StatusEnum.completed.value

        # --- SERVICENOW SPECIFIC PERSISTENCE LOGIC (Raw JSON, No Hermes Envelope) ---
        if has_fc:
            try:
                # Clean tags
                raw_json = accumulated.replace("<fc>", "").replace("</fc>", "").strip()
                payload_dict = json.loads(raw_json)

                # ServiceNow Specific: Save the raw dict as the message content
                message_to_save = json.dumps(payload_dict)

                self._pending_tool_payload = payload_dict
                final_status = StatusEnum.pending_action.value
            except Exception as e:
                LOG.error(f"Error structuring tool calls: {e}")
                # Fallback to accumulated string so no data is lost
                message_to_save = accumulated

        if message_to_save:
            await self.finalize_conversation(
                message_to_save, thread_id, assistant_id, run_id
            )

        if self.project_david_client:
            await asyncio.to_thread(
                self.project_david_client.runs.update_run_status, run_id, final_status
            )
