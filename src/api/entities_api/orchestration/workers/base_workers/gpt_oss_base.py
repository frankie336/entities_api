from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, Optional

from dotenv import load_dotenv
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

# --- DEPENDENCIES ---
from src.api.entities_api.dependencies import get_redis
from src.api.entities_api.orchestration.engine.orchestrator_core import OrchestratorCore

# --- MIXINS ---
from src.api.entities_api.orchestration.mixins.provider_mixins import _ProviderMixins
from entities_api.clients.delta_normalizer import DeltaNormalizer

load_dotenv()
LOG = LoggingUtility()

class GptOssBaseWorker(
    _ProviderMixins,
    OrchestratorCore,
    ABC,
):
    """
    Async Base for GPT-OSS Providers.
    Corrects Turn 2 latency by terminating consumer tool streams immediately.
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
        self._assistant_cache: dict = assistant_cache or extra.get("assistant_cache") or {}
        self.redis = redis or get_redis()
        self.assistant_id = assistant_id
        self.thread_id = thread_id
        self.base_url = base_url or os.getenv("BASE_URL")
        self.api_key = api_key

        self.model_name = extra.get("model_name", "openai/gpt-oss-120b")
        self.max_context_window = extra.get("max_context_window", 131072)
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

    def _get_project_david_client(self, **kwargs) -> Any:
        """Shim for ServiceRegistryMixin to find the David API client."""
        if self._david_client:
            return self._david_client
        from projectdavid import Entity
        self._david_client = Entity(api_key=self.api_key, base_url=self.base_url)
        return self._david_client

    @abstractmethod
    def _get_client_instance(self, api_key: str): pass

    @property
    def assistant_cache(self) -> dict: return self._assistant_cache

    @assistant_cache.setter
    def assistant_cache(self, value: dict) -> None: self._assistant_cache = value

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

        self._current_tool_call_id = None
        self._pending_tool_payload = None
        self._decision_payload = None

        assistant_reply, accumulated, decision_buffer = "", "", ""
        current_block = None

        try:
            if hasattr(self, "_get_model_map") and (mapped := self._get_model_map(model)):
                model = mapped

            raw_ctx = await self._set_up_context_window(
                assistant_id, thread_id, trunk=True,
                structured_tool_call=True, force_refresh=force_refresh, decision_telemetry=False
            )
            cleaned_ctx, extracted_tools = self.prepare_native_tool_context(raw_ctx)

            client = self._get_client_instance(api_key=api_key or self.api_key)
            raw_stream = client.stream_chat_completion(
                messages=cleaned_ctx, model=model,
                tools=None if stream_reasoning else extracted_tools,
                temperature=kwargs.get("temperature", 0.4), **kwargs
            )

            yield json.dumps({"type": "status", "status": "started", "run_id": run_id})

            async for chunk in DeltaNormalizer.async_iter_deltas(raw_stream, run_id):
                if stop_event.is_set(): break
                ctype, ccontent = chunk.get("type"), chunk.get("content") or ""
                safe_content = ccontent if isinstance(ccontent, str) else ""

                if ctype == "content":
                    if current_block == "fc": accumulated += "</fc>"
                    elif current_block == "think": accumulated += "</think>"
                    current_block = None
                    assistant_reply += safe_content
                elif ctype in ("tool_name", "call_arguments"):
                    if current_block != "fc":
                        if current_block == "think": accumulated += "</think>"
                        accumulated += "<fc>"; current_block = "fc"
                elif ctype == "decision":
                    decision_buffer += safe_content
                    if current_block == "fc": accumulated += "</fc>"
                    elif current_block == "think": accumulated += "</think>"
                    current_block = "decision"

                accumulated += safe_content
                if ctype not in ("tool_name", "call_arguments"):
                    yield json.dumps(chunk)
                await self._shunt_to_redis_stream(redis, stream_key, chunk)

            if current_block == "fc": accumulated += "</fc>"
            elif current_block == "think": accumulated += "</think>"

        except Exception as exc:
            LOG.error(f"Stream Exception: {exc}")
            yield json.dumps({"type": "error", "content": str(exc), "run_id": run_id})
        finally:
            stop_event.set()

        yield json.dumps({"type": "status", "status": "complete", "run_id": run_id})

        if decision_buffer:
            try: self._decision_payload = json.loads(decision_buffer.strip())
            except: pass

        yield json.dumps({"type": "status", "status": "processing", "run_id": run_id})

        # Sanitize <fc> blocks
        if "<fc>" in accumulated:
            try:
                fc_pattern = r"<fc>(.*?)</fc>"
                matches = re.findall(fc_pattern, accumulated, re.DOTALL)
                for orig in matches:
                    try: json.loads(orig); continue
                    except: pass
                    fix = re.match(r"^\s*([a-zA-Z0-9_]+)\s*(\{.*)", orig, re.DOTALL)
                    if fix:
                        try:
                            p_args, _ = json.JSONDecoder().raw_decode(fix.group(2))
                            valid = json.dumps({"name": fix.group(1), "arguments": p_args})
                            accumulated = accumulated.replace(f"<fc>{orig}</fc>", f"<fc>{valid}</fc>")
                        except: pass
            except Exception as e: LOG.warning(f"Sanitization warning: {e}")

        # --- RESTORED LOGIC: Capture and Save Function Call Response ---
        has_fc_dict = self.parse_and_set_function_calls(accumulated, assistant_reply)

        # Determine status: If a tool was found, status MUST be pending_action
        final_status = StatusEnum.pending_action.value if has_fc_dict else StatusEnum.completed.value
        message_to_save = assistant_reply

        if has_fc_dict:
            try:
                fc_match = re.search(r"<fc>(.*?)</fc>", accumulated, re.DOTALL)
                if fc_match:
                    payload = json.loads(fc_match.group(1).strip())
                    call_id = f"call_{uuid.uuid4().hex[:8]}"
                    self._current_tool_call_id = call_id
                    self._pending_tool_payload = payload

                    # Construct message for the DB as a valid OpenAI-style tool_calls message
                    tool_calls_structure = [{
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": payload.get("name"),
                            "arguments": json.dumps(payload.get("arguments", {}))
                        }
                    }]
                    message_to_save = json.dumps(tool_calls_structure)
            except:
                message_to_save = accumulated

        # Finalize turn in DB (Atomic status set)
        if message_to_save:
            try:
                await asyncio.wait_for(
                    self.finalize_conversation(
                        message_to_save, thread_id, assistant_id, run_id,
                        final_status=final_status
                    ),
                    timeout=20,
                )
            except Exception as e:
                LOG.error(f"finalize_conversation failed for run {run_id}: {e}")

        # CRITICAL: Invalidate the context cache in Redis.
        # This ensures Turn 2 rebuilt history includes the Assistant's Tool Call and the Tool Result.
        if redis:
            cache_key = f"thread:{thread_id}:context"
            await asyncio.to_thread(redis.delete, cache_key)
            LOG.debug(f"Invalidated context cache for thread {thread_id}")


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

        # --- TURN 1 ---
        async for chunk in self.stream(
            thread_id, message_id, run_id, assistant_id, model, api_key=api_key, **kwargs
        ):
            yield chunk

        # --- TOOL HANDLING ---
        fc_payload = self.get_function_call_state()

        if fc_payload and isinstance(fc_payload, dict):
            fc_name = fc_payload.get("name")
            PLATFORM_TOOLS = {"code_interpreter", "computer", "file_search"}

            # 1. Yield manifest / Execute platform tool
            async for chunk in self.process_tool_calls(
                thread_id, run_id, assistant_id,
                tool_call_id=self._current_tool_call_id,
                model=model, api_key=api_key, decision=self._decision_payload
            ):
                yield chunk

            # 2. Strategy Split
            if fc_name in PLATFORM_TOOLS:
                # STAY ON THE LINE for platform tools
                self.set_tool_response_state(False)
                self.set_function_call_state(None)
                self._current_tool_call_id = None

                # Perform Turn 2 Inference immediately
                async for chunk in self.stream(
                    thread_id, None, run_id, assistant_id, model,
                    force_refresh=True, api_key=api_key, **kwargs
                ):
                    yield chunk
            else:
                # HANG UP for Consumer tools
                # The manifest has been yielded. By returning, we close the stream
                # so the client can POST results and start a new request.
                LOG.info(f"Consumer turn finished for {fc_name}. Hanging up.")
                return
