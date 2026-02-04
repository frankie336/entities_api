from __future__ import annotations

import asyncio
import json
import os
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, Optional

from dotenv import load_dotenv
from projectdavid_common.constants import PLATFORM_TOOLS
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


class DeepSeekBaseWorker(
    _ProviderMixins,
    OrchestratorCore,
    ABC,
):
    """
    Async Base for DeepSeek Providers.
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

        self.model_name = extra.get("model_name", "deepseek-ai/DeepSeek-V3")
        self.max_context_window = extra.get("max_context_window", 128000)
        self.threshold_percentage = extra.get("threshold_percentage", 0.8)

        self._current_tool_call_id: str | None = None
        self._pending_tool_payload: Optional[Dict[str, Any]] = None
        self._decision_payload: Optional[Dict[str, Any]] = None

        self.setup_services()

        # Ensure mixin stubs exist if failed to load (Standardized from GptOss)
        if not hasattr(self, "get_function_call_state"):
            LOG.error("CRITICAL: ToolRoutingMixin failed to load.")
            self.get_function_call_state = lambda: None
            self.set_function_call_state = lambda x: None
            self.set_tool_response_state = lambda x: None

        LOG.debug("Hyperbolic-Ds1 provider ready (assistant=%s)", assistant_id)

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
        stream_reasoning: bool = True,
        api_key: str | None = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        redis = self.redis
        stream_key = f"stream:{run_id}"
        stop_event = self.start_cancellation_monitor(run_id)

        # Early Variable Initialization
        self._current_tool_call_id = None
        self._pending_tool_payload = None
        self._decision_payload = None

        accumulated: str = ""
        assistant_reply: str = ""
        reasoning_reply: str = ""
        decision_buffer: str = ""
        current_block: str | None = None

        try:
            if hasattr(self, "_get_model_map") and (
                mapped := self._get_model_map(model)
            ):
                model = mapped

            # Async Context Setup
            ctx = await self._set_up_context_window(
                assistant_id, thread_id, trunk=True, force_refresh=force_refresh
            )

            # DeepSeek Specific: R1 System Message Amendment
            if model == "deepseek-ai/DeepSeek-R1":
                # FIX: Await this call as it likely involves async DB/Mixin logic now
                amended = await self._build_amended_system_message(
                    assistant_id=assistant_id
                )
                ctx = self.replace_system_message(
                    ctx, json.dumps(amended, ensure_ascii=False)
                )

            if not api_key:
                yield json.dumps({"type": "error", "content": "Missing API key."})
                return

            yield json.dumps({"type": "status", "status": "started", "run_id": run_id})

            # -----------------------------------------------------------
            # STANDARDIZED CLIENT EXECUTION
            # -----------------------------------------------------------
            client = self._get_client_instance(api_key=api_key)
            raw_stream = client.stream_chat_completion(
                messages=ctx,
                model=model,
                max_tokens=10000,
                temperature=kwargs.get("temperature", 0.6),
                stream=True,
                # Note: DeepSeek legacy worker does not pass native 'tools' list,
                # relying on prompt/XML parsing instead.
            )
            # -----------------------------------------------------------

            async for chunk in DeltaNormalizer.async_iter_deltas(raw_stream, run_id):
                if stop_event.is_set():
                    break

                ctype = chunk.get("type")
                ccontent = chunk.get("content") or ""

                # --- DEEPSEEK SPECIFIC PARSING LOGIC (MAINTAINED AS IS) ---
                if ctype == "content":
                    if current_block == "fc":
                        accumulated += "</fc>"
                    elif current_block == "think":
                        accumulated += "</think>"
                    # Note: We don't add </decision> to 'accumulated' because
                    # we want to filter it out of the visible history.
                    current_block = None
                    assistant_reply += ccontent
                    accumulated += ccontent

                elif ctype == "call_arguments":
                    if current_block != "fc":
                        if current_block == "think":
                            accumulated += "</think>"
                        accumulated += "<fc>"
                        current_block = "fc"
                    accumulated += ccontent

                elif ctype == "reasoning":
                    if current_block != "think":
                        if current_block == "fc":
                            accumulated += "</fc>"
                        accumulated += "<think>"
                        current_block = "think"
                    reasoning_reply += ccontent

                elif ctype == "decision":
                    # We are in decision mode. We DO NOT add this to 'accumulated'
                    decision_buffer += ccontent

                    if current_block == "fc":
                        accumulated += "</fc>"
                    elif current_block == "think":
                        accumulated += "</think>"
                    current_block = "decision"

                # Selective Yielding
                if ctype == "call_arguments":
                    continue

                yield json.dumps(chunk)
                await self._shunt_to_redis_stream(redis, stream_key, chunk)

            # Close blocks
            if current_block == "fc":
                accumulated += "</fc>"
            elif current_block == "think":
                accumulated += "</think>"

        except Exception as exc:
            LOG.error(f"DEBUG: Stream Exception: {exc}")
            err = {
                "type": "error",
                "content": f"DeepSeek stream error: {exc}",
                "run_id": run_id,
            }
            yield json.dumps(err)
            await self._shunt_to_redis_stream(redis, stream_key, err)
        finally:
            stop_event.set()

        # --- VALIDATE DECISION PAYLOAD ---
        if decision_buffer:
            try:
                cleaned_decision = decision_buffer.strip()
                self._decision_payload = json.loads(cleaned_decision)
                LOG.info(f"Decision payload validated: {self._decision_payload}")
            except Exception as e:
                LOG.error(f"Failed to parse decision payload: {e}")

        # Keep-Alive
        yield json.dumps({"type": "status", "status": "processing", "run_id": run_id})

        # --- DEEPSEEK SPECIFIC PERSISTENCE (NO HERMES ENVELOPE) ---
        has_fc = self.parse_and_set_function_calls(accumulated, assistant_reply)
        message_to_save = assistant_reply
        final_status = StatusEnum.completed.value

        if has_fc:
            try:
                # Clean tags - DeepSeek Specific Logic
                raw_json = accumulated.replace("<fc>", "").replace("</fc>", "").strip()
                payload_dict = json.loads(raw_json)
                message_to_save = json.dumps(payload_dict)
                self._pending_tool_payload = payload_dict
                final_status = StatusEnum.pending_action.value
            except Exception as e:
                LOG.error(f"Error parsing raw tool JSON: {e}")
                message_to_save = accumulated

        if message_to_save:
            await self.finalize_conversation(
                message_to_save, thread_id, assistant_id, run_id
            )

        if self.project_david_client:
            await asyncio.to_thread(
                self.project_david_client.runs.update_run_status, run_id, final_status
            )

        if not has_fc:
            yield json.dumps({"type": "status", "status": "complete", "run_id": run_id})
