# src/api/entities_api/workers/gpt_oss_worker.py
from __future__ import annotations

import asyncio
import json
import os
import queue as _queue_mod
import re
import threading
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, Generator, List, Optional, Union

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
        delete_ephemeral_thread: bool = False,
        assistant_cache_service: Optional[AssistantCache] = None,
        **extra,
    ) -> None:

        # 1. Config & Dependencies
        self.api_key = api_key or extra.get("api_key")
        # ephemeral worker config
        # These objects are used for deep search and engineering flows
        self.is_deep_research = None
        self._scratch_pad_thread = None
        self._batfish_owner_user_id: str | None = None

        # --- NEW: Engineer flow tracking variables ---
        self.is_engineer = None

        self._delete_ephemeral_thread = delete_ephemeral_thread or extra.get(
            "delete_ephemeral_thread"
        )
        self.ephemeral_supervisor_id = None
        self._delegation_api_key = self.api_key

        # ---[FIX 3] Missing Init Property ---
        self._research_worker_thread = None
        self._worker_thread = None

        # 1. Setup Redis
        self.redis = redis or get_redis_sync()

        # 2. Setup Cache Service
        if assistant_cache_service:
            self._assistant_cache = assistant_cache_service
        elif "assistant_cache" in extra and isinstance(extra["assistant_cache"], AssistantCache):
            self._assistant_cache = extra["assistant_cache"]

        # 3. Setup Config
        legacy_config = extra.get("assistant_config") or extra.get("assistant_cache")
        self.assistant_config: Dict[str, Any] = (
            legacy_config if isinstance(legacy_config, dict) else {}
        )

        self._david_client: Any = None
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
        stream_reasoning: bool = False,
        api_key: str | None = None,
        **kwargs,
    ) -> AsyncGenerator[Union[str, StreamEvent], None]:

        # -----------------------------------
        # Ephemeral supervisor
        # -----------------------------------
        self._run_user_id = None
        self.ephemeral_supervisor_id = None
        self._delegation_api_key = api_key

        # ---[FIX 1] Scratchpad Variable Initialization ---
        self._scratch_pad_thread = None

        redis = self.redis
        stream_key = f"stream:{run_id}"
        stop_event = self.start_cancellation_monitor(run_id)

        # --- [FIX] Capture original assistant_id BEFORE any identity swap ---
        _original_assistant_id = assistant_id

        # 1. State Initialization
        self._current_tool_call_id = None
        self._pending_tool_payload = None
        self._decision_payload = None
        self._tool_queue: List[Dict] = []

        accumulated: str = ""
        assistant_reply: str = ""
        decision_buffer: str = ""
        current_block: str | None = None

        pre_mapped_model = model
        try:
            if hasattr(self, "_get_model_map") and (mapped := self._get_model_map(model)):
                model = mapped

            self.assistant_id = assistant_id
            await self._ensure_config_loaded()

            # ------------------------------------------------------------------
            # 3. ROLE FLAG EXTRACTION
            # Read all role signals from the assistant's normalized config.
            # ------------------------------------------------------------------
            self.is_deep_research = self.assistant_config.get("deep_research", False)
            self.is_engineer = self.assistant_config.get("is_engineer", False)

            agent_mode_setting = self.assistant_config.get("agent_mode", False)
            decision_telemetry = self.assistant_config.get("decision_telemetry", True)

            # Default web_access from config
            web_access_setting = self.assistant_config.get("web_access", False)

            # Extract from meta_data for dynamic ephemeral flags
            raw_meta = self.assistant_config.get("meta_data", {})

            # Worker role flags
            is_worker_val = raw_meta.get(
                "is_research_worker", raw_meta.get("research_worker_calling", False)
            )
            research_worker_setting = str(
                is_worker_val
            ).lower() == "true" or self.assistant_config.get("is_research_worker", False)

            # Check for "junior_engineer"
            is_junior_val = raw_meta.get(
                "junior_engineer", raw_meta.get("junior_engineer_calling", False)
            )
            junior_engineer_setting = str(is_junior_val).lower() == "true"

            # ------------------------------------------------------------------
            # 4. ROLE CONFLICT RESOLUTION
            # Exactly one role is active per invocation.
            # ------------------------------------------------------------------
            if self.is_engineer:
                # SENIOR ENGINEER (SUPERVISOR)
                web_access_setting = False
                research_worker_setting = False
                junior_engineer_setting = False
                self.is_deep_research = False

            elif self.is_deep_research:
                # RESEARCH SUPERVISOR
                web_access_setting = False
                research_worker_setting = False
                junior_engineer_setting = False

            elif research_worker_setting:
                # RESEARCH WORKER
                web_access_setting = True
                junior_engineer_setting = False

            elif junior_engineer_setting:
                # JUNIOR NETWORK ENGINEER
                web_access_setting = False
                research_worker_setting = False

            LOG.critical(
                "██████[ROLE CONFIG] "
                "SeniorEngineer=%s | "
                "DeepResearch=%s | "
                "ResearchWorker=%s | "
                "JuniorEngineer=%s | "
                "WebAccess=%s ██████",
                self.is_engineer,
                self.is_deep_research,
                research_worker_setting,
                junior_engineer_setting,
                web_access_setting,
            )

            # ------------------------------------------------------------------
            # CAPTURE REAL USER ID — before any identity swap mutates state.
            # ------------------------------------------------------------------
            try:
                run = await self._native_exec.retrieve_run(run_id)
                self._run_user_id = run.user_id

                meta = run.meta_data or {}

                meta_owner = meta.get("batfish_owner_user_id")
                meta_scratchpad = meta.get("scratch_pad_thread")

                if self._batfish_owner_user_id is None:
                    self._batfish_owner_user_id = meta_owner or run.user_id

                if self._scratch_pad_thread is None and meta_scratchpad:
                    self._scratch_pad_thread = meta_scratchpad

                LOG.info(
                    "STREAM ▸ Captured run_user_id=%s | batfish_owner=%s | scratch_pad_thread=%s",
                    self._run_user_id,
                    self._batfish_owner_user_id,
                    self._scratch_pad_thread,
                )
            except Exception as e:
                self._run_user_id = None
                LOG.warning("STREAM ▸ Could not resolve run_user_id: %s", e)

            # ------------------------------------------------------------------
            # 5. IDENTITY SWAP & RELOAD (Supervisor roles only)
            # ------------------------------------------------------------------
            await self._handle_role_based_identity_swap(requested_model=pre_mapped_model)

            # --- CRITICAL FIX: Reload config if identity was swapped! ---
            if self.assistant_id != _original_assistant_id:
                LOG.info(
                    f"Identity swapped from {_original_assistant_id} to {self.assistant_id}. Reloading config."
                )
                await self._ensure_config_loaded()

            # ------------------------------------------------------------------
            # SCRATCHPAD THREAD PINNING
            # ------------------------------------------------------------------
            if not self._scratch_pad_thread:
                self._scratch_pad_thread = thread_id

            LOG.info("STREAM ▸ Scratchpad thread pinned to: %s", self._scratch_pad_thread)

            # 2. Context Setup
            raw_ctx = await self._set_up_context_window(
                assistant_id=self.assistant_id,
                thread_id=thread_id,
                trunk=True,
                structured_tool_call=True,
                force_refresh=force_refresh,
                agent_mode=agent_mode_setting,
                decision_telemetry=decision_telemetry,
                web_access=web_access_setting,
                deep_research=self.is_deep_research,
                engineer=self.is_engineer,
                research_worker=research_worker_setting,
                junior_engineer=junior_engineer_setting,
            )

            # GPT-OSS Specific: Prepare native tool context
            cleaned_ctx, extracted_tools = self.prepare_native_tool_context(raw_ctx)

            if not api_key:
                yield json.dumps({"type": "error", "content": "Missing API key."})
                return

            client = self._get_client_instance(api_key=api_key)

            LOG.info(f"\nRAW_CTX_DUMP:\n{json.dumps(cleaned_ctx, indent=2, ensure_ascii=False)}")

            raw_stream = client.stream_chat_completion(
                messages=cleaned_ctx,
                model=model,
                tools=None if stream_reasoning else extracted_tools,
                temperature=kwargs.get("temperature", 0.4),
                **kwargs,
            )

            yield json.dumps({"type": "status", "status": "started", "run_id": run_id})

            # 3. Stream Loop (Using Helper)
            async for chunk in DeltaNormalizer.async_iter_deltas(raw_stream, run_id):
                if stop_event.is_set():
                    break

                # Delegate state management to helper
                (
                    current_block,
                    accumulated,
                    assistant_reply,
                    decision_buffer,
                    should_skip,
                ) = self._handle_chunk_accumulation(
                    chunk, current_block, accumulated, assistant_reply, decision_buffer
                )

                if should_skip:
                    continue

                yield json.dumps(chunk)
                await self._shunt_to_redis_stream(redis, stream_key, chunk)

            # Cleanup open tags
            if current_block:
                accumulated += f"</{current_block}>"

            # =========================================================================
            # POST-STREAM PROCESSING
            # =========================================================================

            # --- SYNC-REPLICA 2: Validate Decision Payload ---
            if decision_buffer:
                try:
                    self._decision_payload = json.loads(decision_buffer.strip())
                    LOG.info(f"Decision payload validated: {self._decision_payload}")
                except Exception as e:
                    LOG.error(f"Failed to parse decision payload: {e}")

            # Keep-Alive Heartbeat
            yield json.dumps({"type": "status", "status": "processing", "run_id": run_id})

            # --- SYNC-REPLICA 3: Post-Stream Sanitization ---
            # (Preserved specifically for GPT-OSS malformed tags)
            if "<fc>" in accumulated:
                try:
                    fc_pattern = r"<fc>(.*?)</fc>"
                    matches = re.findall(fc_pattern, accumulated, re.DOTALL)
                    for original_content in matches:
                        try:
                            json.loads(original_content)
                            continue
                        except json.JSONDecodeError:
                            pass

                        fix_match = re.match(
                            r"^\s*([a-zA-Z0-9_]+)\s*(\{.*)", original_content, re.DOTALL
                        )
                        if fix_match:
                            func_name, func_args = fix_match.group(1), fix_match.group(2)
                            try:
                                parsed_args, _ = json.JSONDecoder().raw_decode(func_args)
                                valid_payload = json.dumps(
                                    {"name": func_name, "arguments": parsed_args}
                                )
                                accumulated = accumulated.replace(
                                    f"<fc>{original_content}</fc>",
                                    f"<fc>{valid_payload}</fc>",
                                )
                            except:
                                pass
                except Exception as e:
                    LOG.error(f"Error during tool call sanitization: {e}")

            tool_calls_batch = self.parse_and_set_function_calls(accumulated, assistant_reply)
            message_to_save = assistant_reply
            final_status = StatusEnum.completed.value

            # --- SYNC-REPLICA 5: Structure and Override Save Message ---
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
                LOG.info(f"\n🚀[L3 AGENT MANIFEST] Turn 1 Batch of {len(tool_calls_structure)}")
                for item in tool_calls_structure:
                    LOG.info(f"   ▸ Tool: {item['function']['name']} | ID: {item['id']}")

            # Persistence: Assistant Plan/Actions saved to Thread
            if message_to_save:
                # [FIX]: Use self.assistant_id to save under the supervisor's ID
                await self.finalize_conversation(
                    message_to_save, thread_id, self.assistant_id, run_id
                )

            await self._native_exec.update_run_status(run_id, final_status)

            if not tool_calls_batch:
                yield json.dumps({"type": "status", "status": "complete", "run_id": run_id})

        except Exception as exc:
            LOG.error(f"DEBUG: Stream Exception: {exc}")
            err = {"type": "error", "content": f"Stream error: {exc}", "run_id": run_id}
            yield json.dumps(err)
            await self._shunt_to_redis_stream(redis, stream_key, err)

        finally:
            # 1. Ensure cancellation monitor is stopped
            stop_event.set()

    def stream_sync(
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
    ) -> Generator[str, None, None]:
        """
        Synchronous wrapper around the async stream() method.

        Supports two calling contexts:

          A) No running event loop (standard sync caller, CLI, Celery worker, test):
             Creates a dedicated event loop, drives the async generator to completion,
             then tears it down cleanly. Zero thread overhead.

          B) Running event loop already exists (sync function called from within a
             thread that shares a loop with async code):
             Spins up a fresh event loop in a background thread and uses a Queue to
             ferry yielded values back to the calling thread, keeping the two loops
             fully isolated.

        Yields the same JSON-serialised strings as stream().
        """
        kwargs.update(
            force_refresh=force_refresh,
            stream_reasoning=stream_reasoning,
            api_key=api_key,
        )

        # ------------------------------------------------------------------
        # Path A — no running loop in this thread
        # ------------------------------------------------------------------
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                agen = self.stream(thread_id, message_id, run_id, assistant_id, model, **kwargs)
                while True:
                    try:
                        yield loop.run_until_complete(agen.__anext__())
                    except StopAsyncIteration:
                        break
            finally:
                try:
                    loop.run_until_complete(loop.shutdown_asyncgens())
                except Exception:
                    pass
                loop.close()
                asyncio.set_event_loop(None)
            return

        # ------------------------------------------------------------------
        # Path B — a loop is already running; isolate in a background thread
        # ------------------------------------------------------------------
        _SENTINEL = object()
        queue_ref: list = []

        def _run_in_thread() -> None:
            """Owns its own loop; pushes items onto a thread-safe queue."""
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            q: _queue_mod.Queue = _queue_mod.Queue()
            queue_ref.append(q)

            async def _drain() -> None:
                agen = self.stream(thread_id, message_id, run_id, assistant_id, model, **kwargs)
                try:
                    async for item in agen:
                        q.put(item)
                finally:
                    q.put(_SENTINEL)

            try:
                new_loop.run_until_complete(_drain())
            finally:
                try:
                    new_loop.run_until_complete(new_loop.shutdown_asyncgens())
                except Exception:
                    pass
                new_loop.close()

        t = threading.Thread(target=_run_in_thread, daemon=True)
        t.start()

        # Spin until the background thread has created and registered the queue
        while not queue_ref:
            time.sleep(0.001)

        q = queue_ref[0]
        while True:
            item = q.get()
            if item is _SENTINEL:
                break
            yield item

        t.join()
