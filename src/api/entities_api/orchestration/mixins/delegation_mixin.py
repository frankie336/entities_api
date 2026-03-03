from __future__ import annotations

import asyncio
import json
import os
import threading
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Callable, Dict, Optional

from projectdavid.events import ScratchpadEvent
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from src.api.entities_api.services.native_execution_service import \
    NativeExecutionService
from src.api.entities_api.utils.assistant_manager import AssistantManager

LOG = LoggingUtility()

_TERMINAL_RUN_STATES = {"completed", "failed", "cancelled", "expired"}
_WORKER_RUN_TIMEOUT = 1200
_WORKER_POLL_INTERVAL = 2.0


class DelegationMixin:

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._delegation_api_key = None
        self._delete_ephemeral_thread = False
        self._delegation_model = None
        self._research_worker_thread = None
        self._scratch_pad_thread = None
        self._run_user_id = None
        self._batfish_owner_user_id = None
        self._native_exec_svc: Optional[NativeExecutionService] = None

    # ------------------------------------------------------------------
    # NATIVE EXECUTION SERVICE — lazy singleton per mixin instance
    # Instantiated on first access; never re-created.  Avoids adding
    # NativeExecutionService to the MRO while still reusing the same
    # Redis / DB connections across calls within a single request.
    #
    # Uses a single leading underscore (not double) to avoid Python's
    # name-mangling, which would make the attribute invisible to
    # subclasses and break the lazy-init guard.
    # ------------------------------------------------------------------

    @property
    def _native_exec(self) -> NativeExecutionService:
        # Use getattr so this works even when DelegationMixin.__init__ was
        # never called (e.g. TogetherQwenWorker and other concrete subclasses
        # that do not call super().__init__() through the full MRO).
        if getattr(self, "_native_exec_svc", None) is None:
            self._native_exec_svc = NativeExecutionService()
        return self._native_exec_svc

    @property
    def _assistant_manager(self) -> AssistantManager:
        if getattr(self, "_assistant_manager_svc", None) is None:
            self._assistant_manager_svc = AssistantManager()
        return self._assistant_manager_svc

    # ------------------------------------------------------------------
    # EMISSION HELPER
    # ------------------------------------------------------------------

    def _research_status(self, activity: str, state: str, run_id: str) -> str:
        return json.dumps(
            {
                "type": "research_status",
                "activity": activity,
                "state": state,
                "tool": "delegate_research_task",
                "run_id": run_id,
            }
        )

    # ------------------------------------------------------------------
    # HELPER: Bridges blocking generators to async loop
    # ------------------------------------------------------------------

    async def _stream_sync_generator(
        self, generator_func: Callable, *args, **kwargs
    ) -> AsyncGenerator[Any, None]:
        queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def producer():
            try:
                for item in generator_func(*args, **kwargs):
                    loop.call_soon_threadsafe(queue.put_nowait, item)
                loop.call_soon_threadsafe(queue.put_nowait, None)
            except Exception as e:
                LOG.error(f"🧵 [THREAD-ERR] {e}")
                loop.call_soon_threadsafe(queue.put_nowait, e)

        threading.Thread(target=producer, daemon=True).start()

        while True:
            item = await queue.get()
            if item is None:
                break
            if isinstance(item, Exception):
                raise item
            yield item

    # ------------------------------------------------------------------
    # HELPER: Poll run status until terminal
    # ------------------------------------------------------------------

    async def _wait_for_run_completion(
        self,
        run_id: str,
        thread_id: str,
        timeout: float = _WORKER_RUN_TIMEOUT,
        poll_interval: float = _WORKER_POLL_INTERVAL,
    ) -> str:
        LOG.info(
            "⏳ [DELEGATE] Waiting for worker run %s to complete (timeout=%ss)...",
            run_id,
            timeout,
        )
        elapsed = 0.0
        while elapsed < timeout:
            try:
                # ── REPLACED: was self.project_david_client.runs.retrieve_run(...)
                run = await self._native_exec.retrieve_run(run_id)
                status_value = (
                    run.status.value
                    if hasattr(run.status, "value")
                    else str(run.status)
                )
                LOG.critical(
                    "██████ [DELEGATE_POLL] run_id=%s status=%s elapsed=%.1fs ██████",
                    run_id,
                    status_value,
                    elapsed,
                )
                if status_value in _TERMINAL_RUN_STATES:
                    LOG.critical(
                        "██████ [DELEGATE_POLL] run_id=%s reached terminal state=%s ██████",
                        run_id,
                        status_value,
                    )
                    return status_value
            except Exception as e:
                LOG.warning("⚠️ [DELEGATE_POLL] Error polling run %s: %s", run_id, e)
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        LOG.error("❌ [DELEGATE_POLL] run_id=%s timed out after %ss.", run_id, timeout)
        raise asyncio.TimeoutError(
            f"Worker run {run_id} did not complete within {timeout}s"
        )

    # ------------------------------------------------------------------
    # HELPER: Lifecycle cleanup
    # ------------------------------------------------------------------
    async def _ephemeral_clean_up(
        self, assistant_id: str, thread_id: Optional[str], delete_thread: bool = False
    ):
        LOG.info(f"🧹 [CLEANUP] Assistant: {assistant_id} | Thread: {thread_id}")
        if delete_thread and thread_id:
            try:
                # ── REPLACED: was self.project_david_client.threads.delete_thread(...)
                await self._native_exec.delete_thread(thread_id)
            except Exception as e:
                LOG.warning(f"⚠️ [CLEANUP] Thread delete failed: {e}")
        # TODO: assistant deletion logic goes here when AssistantManager
        # exposes a delete method — scaffold retained as a reminder.

    @asynccontextmanager
    async def _capture_tool_outputs(self, capture_dict: Dict[str, str]):
        original = self.submit_tool_output

        async def intercept(
            thread_id,
            assistant_id,
            tool_call_id,
            content,
            action=None,
            is_error=False,
            **kwargs,
        ):
            capture_dict[tool_call_id] = str(content)
            await original(
                thread_id,
                assistant_id,
                tool_call_id,
                content,
                action,
                is_error,
                **kwargs,
            )

        self.submit_tool_output = intercept
        try:
            yield
        finally:
            self.submit_tool_output = original

    # ------------------------------------------------------------------
    # EPHEMERAL FACTORIES
    # ------------------------------------------------------------------
    async def create_ephemeral_worker_assistant(self):
        return await self._assistant_manager.create_ephemeral_worker_assistant()

    async def create_ephemeral_junior_engineer(self):
        return await self._assistant_manager.create_ephemeral_junior_engineer()

    async def create_ephemeral_thread(self):
        # ── REPLACED: was self.project_david_client.threads.create_thread()
        # Also fixes incorrect participant: SDK passed admin user; we now pass
        # the resolved owner so the ephemeral thread is correctly associated.
        user_id = getattr(self, "_batfish_owner_user_id", None)
        if not user_id:
            raise RuntimeError(
                "create_ephemeral_thread: _batfish_owner_user_id has not been "
                "resolved yet — ensure it is set before calling this method."
            )
        return await self._native_exec.create_thread(user_id=user_id)

    async def create_ephemeral_message(self, thread_id, content, assistant_id):
        # ── REPLACED: was self.project_david_client.messages.create_message(...)
        return await self._native_exec.create_message(
            thread_id=thread_id,
            assistant_id=assistant_id,
            content=content,
        )

    async def create_ephemeral_run(
        self, assistant_id, thread_id, meta_data: Dict | None = None
    ):
        # ── REPLACED: was self.project_david_client.runs.create_run(...)
        # user_id is required by RunService.create_run; use the owner resolved
        # earlier in handle_delegate_research_task and cached on self.
        user_id = getattr(self, "_batfish_owner_user_id", None)
        if not user_id:
            raise RuntimeError(
                "create_ephemeral_run: _batfish_owner_user_id has not been "
                "resolved yet — ensure it is set before calling this method."
            )
        return await self._native_exec.create_run(
            assistant_id=assistant_id,
            thread_id=thread_id,
            user_id=user_id,
            meta_data=meta_data,
        )

    async def _fetch_worker_final_report(
        self,
        thread_id: str,
        max_attempts: int = 5,
        retry_delay: float = 3.0,
    ) -> str | None:
        """
        Fetch the worker's final text report from its thread.

        Retry logic is required because the worker run reaches status=completed
        at elapsed=0.0s — before finalize_conversation has committed the final
        assistant message to the thread. Without retries, the first fetch always
        races against the write and finds either nothing or only tool-call messages.

        Message filtering:
          - Skips non-assistant messages (user, tool results)
          - Skips messages whose content is a JSON array (tool_calls_structure
            saved by finalize_conversation when the last turn was a tool call)
          - Returns the first assistant message with clean text content, scanning
            from newest to oldest
        """
        for attempt in range(1, max_attempts + 1):
            try:
                messages = await self._native_exec.get_formatted_messages(thread_id)

                LOG.critical(
                    "██████ [WORKER_FETCH] attempt=%d thread=%s total_messages=%d ██████",
                    attempt,
                    thread_id,
                    len(messages) if messages else 0,
                )
                for i, msg in enumerate(messages or []):
                    LOG.critical(
                        "██████ [WORKER_FETCH] msg[%d] role=%s tool_calls=%s content_preview=%s ██████",
                        i,
                        msg.get("role"),
                        bool(msg.get("tool_calls")),
                        str(msg.get("content", ""))[:120],
                    )

                if not messages:
                    LOG.warning(
                        "[WORKER_FETCH] attempt=%d — no messages in thread %s",
                        attempt,
                        thread_id,
                    )
                else:
                    for msg in reversed(messages):
                        role = msg.get("role")
                        content = msg.get("content")
                        tool_calls = msg.get("tool_calls")

                        if role != "assistant":
                            continue

                        if tool_calls:
                            continue

                        if not isinstance(content, str) or not content.strip():
                            continue

                        stripped = content.strip()
                        if stripped.startswith("[") and stripped.endswith("]"):
                            try:
                                parsed = json.loads(stripped)
                                if isinstance(parsed, list) and all(
                                    isinstance(item, dict) and "type" in item
                                    for item in parsed
                                ):
                                    LOG.info(
                                        "[WORKER_FETCH] Skipping tool_calls_structure "
                                        "saved as content string."
                                    )
                                    continue
                            except (json.JSONDecodeError, ValueError):
                                pass

                        LOG.info(
                            "✅ [WORKER_FETCH] attempt=%d found report (length=%d): %s...",
                            attempt,
                            len(stripped),
                            stripped[:100],
                        )
                        return stripped

                    LOG.warning(
                        "[WORKER_FETCH] attempt=%d — no qualifying text message found. "
                        "Retrying in %.1fs...",
                        attempt,
                        retry_delay,
                    )

            except Exception as e:
                LOG.exception(
                    "❌ [WORKER_FETCH] attempt=%d — exception fetching messages: %s",
                    attempt,
                    e,
                )

            if attempt < max_attempts:
                await asyncio.sleep(retry_delay)

        LOG.critical(
            "██████ [WORKER_FETCH] EXHAUSTED %d attempts for thread %s — returning None ██████",
            max_attempts,
            thread_id,
        )
        return None

    # ------------------------------------------------------------------
    # HANDLER 1: Research Delegation — RESTORED working structure
    # Additions: origin_user_id resolution + metadata stamp on ephemeral run
    # ------------------------------------------------------------------
    async def handle_delegate_research_task(
        self, thread_id, run_id, assistant_id, arguments_dict, tool_call_id, decision
    ) -> AsyncGenerator[str, None]:
        """
        Supervisor → Worker research delegation.

        Flow:
          - Spawns an ephemeral worker assistant on its own thread.
          - Streams worker content, reasoning, and scratchpad events back
            through the senior's stream so the backend consumer sees everything
            in a single unified pipe.
          - ScratchpadEvents are intercepted BEFORE the broad attribute guards
            fire — critical ordering that prevents silent swallowing.
          - Intercept payload mirrors _scratchpad_status() exactly — only
            non-None fields are included so the shape is byte-for-byte
            identical to native supervisor scratchpad events. The only
            addition is 'origin: research_worker' for frontend source tagging.
          - Submits the worker's final report back to the supervisor as a
            tool output, completing the delegation loop.

        Prompt note:
          The delegation prompt explicitly forbids memory-based answers and
          mandates tool firing as the first action. This is required because
          Qwen3-class reasoning models will otherwise think through the task
          internally, conclude they already know the answer from training
          weights, and skip all tool calls entirely — producing a one-line
          confirmation with no verified data and no scratchpad entry.
        """

        self._scratch_pad_thread = thread_id
        LOG.info(f"🔄 [DELEGATE] STARTING. Run: {run_id}")

        if isinstance(arguments_dict, str):
            try:
                args = json.loads(arguments_dict)
            except Exception:
                args = {"task": arguments_dict}
        else:
            args = arguments_dict

        yield self._research_status(
            "Initializing delegation worker...", "in_progress", run_id
        )

        action = None
        try:
            # ── REPLACED: was self.project_david_client.actions.create_action(...)
            action = await self._native_exec.create_action(
                tool_name="delegate_research_task",
                run_id=run_id,
                tool_call_id=tool_call_id,
                function_args=arguments_dict,
                decision=decision,
            )
        except Exception as e:
            LOG.error(f"❌[DELEGATE] Action creation failed: {e}")

        ephemeral_worker = None
        ephemeral_thread = None
        execution_had_error = False
        ephemeral_run = None

        try:
            origin_user_id = getattr(self, "_batfish_owner_user_id", None)

            if not origin_user_id:
                # ── REPLACED: was self.project_david_client.runs.retrieve_run(...)
                run_obj = await self._native_exec.retrieve_run(run_id)
                origin_user_id = run_obj.user_id
                self._batfish_owner_user_id = origin_user_id

            LOG.info(
                "RESEARCH_DELEGATE ▸ origin_user_id=%s | scratch_pad_thread=%s",
                origin_user_id,
                self._scratch_pad_thread,
            )

            ephemeral_worker = await self.create_ephemeral_worker_assistant()
            ephemeral_thread = await self.create_ephemeral_thread()
            self._research_worker_thread = ephemeral_thread

            prompt = (
                f"TASK: {args.get('task')}\n"
                f"REQ: {args.get('requirements')}\n\n"
                f"⚠️ MANDATORY EXECUTION RULES — NO EXCEPTIONS:\n"
                f"1. Your FIRST action MUST be tool calls: fire `read_scratchpad()` "
                f"AND `perform_web_search()` simultaneously. Do NOT reason first.\n"
                f"2. Your training knowledge is NOT an acceptable source. "
                f"Every fact MUST come from a live URL retrieved in this session.\n"
                f"3. You MUST call `append_scratchpad` with your verified result "
                f"BEFORE sending any text reply.\n"
                f"4. A ✅ [VERIFIED] entry requires an exact value AND a live source URL. "
                f"No URL = no verification = task failure.\n"
                f"5. Sending a confirmation without having called `append_scratchpad` "
                f"means you have failed. The supervisor cannot see your text — "
                f"only the scratchpad."
            )

            msg = await self.create_ephemeral_message(
                ephemeral_thread.id, prompt, ephemeral_worker.id
            )

            ephemeral_run = await self.create_ephemeral_run(
                ephemeral_worker.id,
                ephemeral_thread.id,
                meta_data={
                    "batfish_owner_user_id": origin_user_id,
                    "scratch_pad_thread": self._scratch_pad_thread,
                },
            )

            LOG.info(
                "RESEARCH_DELEGATE ▸ Stamped meta_data: batfish_owner_user_id=%s | scratch_pad_thread=%s",
                origin_user_id,
                self._scratch_pad_thread,
            )

            yield self._research_status(
                "Worker active. Streaming...", "in_progress", run_id
            )

            LOG.info(f"🔄 [SUPERVISORS_THREAD_ID]: {thread_id}")
            LOG.info(f"🔄 [WORKERS_THREAD_ID]: {ephemeral_thread.id}")

            sync_stream = self.project_david_client.synchronous_inference_stream
            sync_stream.setup(
                thread_id=ephemeral_thread.id,
                assistant_id=ephemeral_worker.id,
                message_id=msg.id,
                run_id=ephemeral_run.id,
                api_key=self._delegation_api_key,
            )

            LOG.critical(
                "🎬 WORKER STREAM STARTING - If you see this but no content chunks, "
                "check process_tool_calls wiring"
            )

            captured_stream_content = ""

            async for event in self._stream_sync_generator(
                sync_stream.stream_events,
                model=self._delegation_model,
            ):
                # ----------------------------------------------------------------
                # ✅ INTERCEPT: ScratchpadEvent
                # MUST come before GUARD 1 — ScratchpadEvent carries a 'tool'
                # attribute which causes the guard to swallow it silently.
                # ----------------------------------------------------------------
                if isinstance(event, ScratchpadEvent):
                    LOG.info(
                        "📋 [DELEGATE] Worker ScratchpadEvent intercepted: "
                        "op=%s state=%s activity=%s",
                        event.operation,
                        event.state,
                        event.activity,
                    )

                    payload = {
                        "type": "scratchpad_status",
                        "run_id": run_id,
                        "operation": event.operation,
                        "state": event.state,
                        "origin": "research_worker",
                    }

                    if event.tool is not None:
                        payload["tool"] = event.tool
                    if event.activity is not None:
                        payload["activity"] = event.activity
                    if event.assistant_id is not None:
                        payload["assistant_id"] = event.assistant_id

                    entry_val = event.entry or event.content or ""
                    if entry_val:
                        payload["entry"] = entry_val

                    yield json.dumps(payload)
                    continue

                # ----------------------------------------------------------------
                # 🛑 GUARD 1: Exclude Status / System Events
                # ----------------------------------------------------------------
                if (
                    hasattr(event, "tool")
                    or hasattr(event, "status")
                    or getattr(event, "type", "") == "status"
                ):
                    continue

                # ----------------------------------------------------------------
                # 🛑 GUARD 2: Exclude Tool Call Argument Frames
                # ----------------------------------------------------------------
                if getattr(event, "tool_calls", None) or getattr(
                    event, "function_call", None
                ):
                    continue

                chunk_content = getattr(event, "content", None) or getattr(
                    event, "text", None
                )
                chunk_reasoning = getattr(event, "reasoning", None)

                if chunk_reasoning:
                    yield json.dumps(
                        {
                            "stream_type": "delegation",
                            "chunk": {
                                "type": "reasoning",
                                "content": chunk_reasoning,
                                "run_id": run_id,
                            },
                        }
                    )

                if chunk_content and isinstance(chunk_content, str):
                    captured_stream_content += chunk_content
                    yield json.dumps(
                        {
                            "stream_type": "delegation",
                            "chunk": {
                                "type": "content",
                                "content": chunk_content,
                                "run_id": run_id,
                            },
                        }
                    )

            yield self._research_status(
                "Worker processing. Waiting for completion...", "in_progress", run_id
            )

            try:
                final_run_status = await self._wait_for_run_completion(
                    run_id=ephemeral_run.id,
                    thread_id=ephemeral_thread.id,
                )
                LOG.info(
                    "✅ [DELEGATE] Worker run completed. Status=%s", final_run_status
                )
            except asyncio.TimeoutError:
                LOG.error("⏳[DELEGATE] Worker run timed out. Attempting fetch anyway.")
                execution_had_error = True
                final_run_status = "timed_out"

            final_content = await self._fetch_worker_final_report(
                thread_id=ephemeral_thread.id
            )

            LOG.critical(
                "██████ [FINAL_THREAD_CONTENT_SUBMITTED_BY_RESEARCH_WORKER]=%s ██████",
                final_content,
            )

            if not final_content:
                LOG.critical(
                    "██████ [DELEGATE_TOTAL_FAILURE] No content generated by the worker ██████"
                )
                final_content = "No report generated by worker."
                execution_had_error = True

            await self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                content=final_content,
                action=action,
                is_error=execution_had_error,
            )

            if action:
                # ── REPLACED: was self.project_david_client.actions.update_action(...)
                await self._native_exec.update_action_status(
                    action.id,
                    (
                        StatusEnum.completed.value
                        if not execution_had_error
                        else StatusEnum.failed.value
                    ),
                )

        except Exception as e:
            execution_had_error = True
            LOG.error(f"❌ [DELEGATE] Error: {e}", exc_info=True)
            yield self._research_status(f"Error: {str(e)}", "error", run_id)

        finally:
            if ephemeral_worker:
                await self._ephemeral_clean_up(
                    ephemeral_worker.id,
                    ephemeral_thread.id if ephemeral_thread else None,
                    self._delete_ephemeral_thread,
                )

            yield self._research_status(
                "Delegation complete.",
                "completed" if not execution_had_error else "error",
                run_id,
            )
