from __future__ import annotations

import asyncio
import json
import os
import re
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
    Migrated to Async-First Architecture following GPT-OSS Gold Standard.
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
        self.api_key = api_key

        self.model_name = extra.get("model_name", "deepseek-ai/DeepSeek-V3")
        self.max_context_window = extra.get("max_context_window", 128000)
        self.threshold_percentage = extra.get("threshold_percentage", 0.8)

        self._current_tool_call_id: str | None = None
        self._pending_tool_payload: Optional[Dict[str, Any]] = None
        self._decision_payload: Optional[Dict[str, Any]] = None

        self.setup_services()

        if not hasattr(self, "get_function_call_state"):
            LOG.error("CRITICAL: ToolRoutingMixin failed to load.")
            self.get_function_call_state = lambda: None
            self.set_function_call_state = lambda x: None
            self.set_tool_response_state = lambda x: None

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

            raw_ctx = await self._set_up_context_window(
                assistant_id,
                thread_id,
                trunk=True,
                structured_tool_call=True,
                force_refresh=force_refresh,
                decision_telemetry=False,
            )

            # --- DeepSeek Specific: R1 System Message Handling ---
            if model == "deepseek-ai/DeepSeek-R1":
                amended = self._build_amended_system_message(assistant_id=assistant_id)
                raw_ctx = self.replace_system_message(
                    raw_ctx, json.dumps(amended, ensure_ascii=False)
                )

            cleaned_ctx, extracted_tools = self.prepare_native_tool_context(raw_ctx)

            if not api_key:
                yield json.dumps({"type": "error", "content": "Missing API key."})
                return

            # --- Standardized Client Execution (GPT-OSS Style) ---
            client = self._get_client_instance(api_key=api_key)

            # Note: We pass extracted_tools only if not using stream_reasoning,
            # or based on your specific logic for DeepSeek.
            # Assuming strictly following GPT-OSS pattern regarding reasoning/tools conflict:
            tools_arg = None if stream_reasoning else extracted_tools

            raw_stream = client.stream_chat_completion(
                messages=raw_ctx,
                model=model,
                # tools=tools_arg,
                temperature=kwargs.get("temperature", 0.6),
                **kwargs,
            )

            yield json.dumps({"type": "status", "status": "started", "run_id": run_id})

            async for chunk in DeltaNormalizer.async_iter_deltas(raw_stream, run_id):
                if stop_event.is_set():
                    break

                ctype = chunk.get("type")
                ccontent = chunk.get("content") or ""
                safe_content = ccontent if isinstance(ccontent, str) else ""

                if ctype == "content":
                    if current_block == "fc":
                        accumulated += "</fc>"
                    elif current_block == "think":
                        accumulated += "</think>"
                    current_block = None
                    assistant_reply += safe_content
                    accumulated += safe_content

                elif ctype in ("tool_name", "call_arguments"):
                    if current_block != "fc":
                        if current_block == "think":
                            accumulated += "</think>"
                        accumulated += "<fc>"
                        current_block = "fc"
                    accumulated += safe_content

                elif ctype == "reasoning":
                    if current_block != "think":
                        if current_block == "fc":
                            accumulated += "</fc>"
                        accumulated += "<think>"
                        current_block = "think"
                    reasoning_reply += safe_content

                elif ctype == "decision":
                    # DeepSeek specific: Accumulate decision buffer but do NOT add to visible accumulated/reply
                    decision_buffer += safe_content

                    if current_block == "fc":
                        accumulated += "</fc>"
                    elif current_block == "think":
                        accumulated += "</think>"
                    current_block = "decision"

                # Yield events (filtering out raw call_arguments if desired, usually handled by Normalizer)
                if ctype not in ("tool_name", "call_arguments"):
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

        yield json.dumps({"type": "status", "status": "complete", "run_id": run_id})

        # --- SYNC-REPLICA 2: Validate Decision Payload ---
        if decision_buffer:
            try:
                cleaned_decision = decision_buffer.strip()
                self._decision_payload = json.loads(cleaned_decision)
                LOG.info(f"Decision payload validated: {self._decision_payload}")
            except Exception as e:
                LOG.error(f"Failed to parse decision payload: {e}")

        # Keep-Alive Heartbeat
        yield json.dumps({"type": "status", "status": "processing", "run_id": run_id})

        # --- SYNC-REPLICA 4: Detection & Mixin State Sync ---
        has_fc = self.parse_and_set_function_calls(accumulated, assistant_reply)

        message_to_save = assistant_reply
        final_status = StatusEnum.completed.value

        # --- SYNC-REPLICA 5: Persistence (DEEPSEEK STYLE) ---
        # Note: We PRESERVE the raw JSON persistence logic from the original DeepSeek worker
        # instead of adopting the GPT-OSS Hermes envelope.
        if has_fc:
            try:
                # Clean tags
                raw_json = accumulated.replace("<fc>", "").replace("</fc>", "").strip()
                payload_dict = json.loads(raw_json)

                # DeepSeek saves the raw dictionary structure directly
                message_to_save = json.dumps(payload_dict)
                self._pending_tool_payload = payload_dict
                final_status = StatusEnum.pending_action.value

            except Exception as e:
                LOG.error(f"Error parsing raw tool JSON: {e}")
                message_to_save = accumulated

        # --- SYNC-REPLICA 6: Persistence ---
        if message_to_save:
            await self.finalize_conversation(
                message_to_save, thread_id, assistant_id, run_id
            )

        if self.project_david_client:
            await asyncio.to_thread(
                self.project_david_client.runs.update_run_status, run_id, final_status
            )

    async def process_conversation(
        self,
        thread_id: str,
        message_id: Optional[str],
        run_id: str,
        assistant_id: str,
        model: Any,
        api_key: Optional[str] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:

        # Turn 1
        async for chunk in self.stream(
            thread_id,
            message_id,
            run_id,
            assistant_id,
            model,
            api_key=api_key,
            **kwargs,
        ):
            yield chunk

        # Turn 2 / Check Tools
        if self.get_function_call_state():
            fc_payload = self.get_function_call_state()
            fc_name = fc_payload.get("name") if isinstance(fc_payload, dict) else None

            # 1. Execute/Manifest
            async for chunk in self.process_tool_calls(
                thread_id,
                run_id,
                assistant_id,
                tool_call_id=self._current_tool_call_id,
                model=model,
                api_key=api_key,
                decision=self._decision_payload,
            ):
                yield chunk

            # 2. Strategy Split (Migrated from GPT-OSS Standard)
            if fc_name in PLATFORM_TOOLS:
                self.set_tool_response_state(False)
                self.set_function_call_state(None)

                # Clear specific payloads
                if hasattr(self, "_pending_tool_payload"):
                    self._pending_tool_payload = None
                if hasattr(self, "_decision_payload"):
                    self._decision_payload = None

                async for chunk in self.stream(
                    thread_id,
                    None,
                    run_id,
                    assistant_id,
                    model,
                    force_refresh=True,
                    api_key=api_key,
                    **kwargs,
                ):
                    yield chunk
            else:
                # Consumer tools: connection MUST close here so client can execute and start Request 2.
                LOG.info(f"Consumer turn finished for {fc_name}. Request Complete.")
                return
