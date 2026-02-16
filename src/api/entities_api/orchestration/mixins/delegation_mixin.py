from __future__ import annotations

import asyncio
import json
import threading
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Callable, Dict

from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from src.api.entities_api.utils.assistant_manager import AssistantManager

LOG = LoggingUtility()


class DelegationMixin:
    """
    Spins up an ephemeral Worker Loop using the project_david_client strictly.
    Lifecycle matches the central Orchestrator stream logic.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._delegation_api_key = None
        self._delete_ephemeral_thread = False
        self._delegation_model = None

    # --- HELPER: Bridges blocking generators to async loop (Fixes uvloop error) ---
    async def _stream_sync_generator(
        self, generator_func: Callable, *args, **kwargs
    ) -> AsyncGenerator[Any, None]:
        """
        Runs a synchronous generator in a background thread and yields items asynchronously.
        This removes the need for bulky 'background_stream_worker' logic in the main handler.
        """
        queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def producer():
            try:
                # Run the blocking stream here
                for item in generator_func(*args, **kwargs):
                    loop.call_soon_threadsafe(queue.put_nowait, item)
                loop.call_soon_threadsafe(queue.put_nowait, None)  # Sentinel
            except Exception as e:
                LOG.error(f"🧵 [THREAD-ERR] {e}")
                loop.call_soon_threadsafe(queue.put_nowait, e)

        # Start thread
        threading.Thread(target=producer, daemon=True).start()

        # Consume queue
        while True:
            item = await queue.get()
            if item is None:
                break
            if isinstance(item, Exception):
                raise item
            yield item

    # ... [Keep existing helpers: _ephemeral_clean_up, _capture_tool_outputs, etc.] ...

    async def _ephemeral_clean_up(
        self, assistant_id: str, thread_id: str, delete_thread: bool = False
    ):
        LOG.info(f"🧹 [CLEANUP] Assistant: {assistant_id} | Thread: {thread_id}")
        if delete_thread:
            try:
                await asyncio.to_thread(
                    self.project_david_client.threads.delete_thread, thread_id=thread_id
                )
            except Exception as e:
                LOG.warning(f"⚠️ [CLEANUP] Thread delete failed: {e}")
        try:
            manager = AssistantManager()
            await manager.delete_assistant(assistant_id=assistant_id, permanent=True)
        except Exception as e:
            LOG.error(f"❌ [CLEANUP] Assistant delete failed: {e}")

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

    async def create_ephemeral_worker_assistant(self):
        manager = AssistantManager()
        return await manager.create_ephemeral_worker_assistant()

    async def create_ephemeral_thread(self):
        return await asyncio.to_thread(self.project_david_client.threads.create_thread)

    async def create_ephemeral_message(self, thread_id, content, assistant_id):
        return await asyncio.to_thread(
            self.project_david_client.messages.create_message,
            thread_id=thread_id,
            assistant_id=assistant_id,
            content=content,
        )

    async def create_ephemeral_run(self, assistant_id, thread_id):
        return await asyncio.to_thread(
            self.project_david_client.runs.create_run,
            assistant_id=assistant_id,
            thread_id=thread_id,
        )

    async def _fetch_worker_final_report(self, thread_id: str) -> str | None:
        # ... [Keep your existing implementation here] ...
        try:
            messages = await asyncio.to_thread(
                self.project_david_client.messages.get_formatted_messages,
                thread_id=thread_id,
            )
            if not messages:
                return None
            for msg in reversed(messages):
                if isinstance(msg.get("content"), str):
                    return msg["content"]
                # ... (rest of your logic) ...
            return None
        except Exception:
            return None

    # --- CLEANED MAIN HANDLER ---
    async def handle_delegate_research_task(
        self, thread_id, run_id, assistant_id, arguments_dict, tool_call_id, decision
    ) -> AsyncGenerator[str, None]:

        LOG.info(f"🔄 [DELEGATE] STARTING. Run: {run_id}")

        # 1. Parse Arguments
        if isinstance(arguments_dict, str):
            try:
                args = json.loads(arguments_dict)
            except:
                args = {"task": arguments_dict}
        else:
            args = arguments_dict

        # 2. Yield Initial Status
        yield json.dumps(
            {
                "type": "activity",
                "activity": "Initializing delegation worker...",
                "state": "in_progress",
                "tool": "delegate_research_task",
                "run_id": run_id,
            }
        )

        # 3. Create Action (DB)
        action = None
        try:
            action = await asyncio.to_thread(
                self.project_david_client.actions.create_action,
                tool_name="delegate_research_task",
                run_id=run_id,
                tool_call_id=tool_call_id,
                function_args=arguments_dict,
                decision=decision,
            )
        except Exception as e:
            LOG.error(f"❌ [DELEGATE] Action creation failed: {e}")

        ephemeral_worker = None
        execution_had_error = False
        captured_stream_content = ""  # <--- NEW: Buffer to prevent empty reports

        try:
            # 4. Setup Ephemeral Assistant & Thread
            ephemeral_worker = await self.create_ephemeral_worker_assistant()
            ephemeral_thread = await self.create_ephemeral_thread()

            prompt = f"TASK: {args.get('task')}\nREQ: {args.get('requirements')}"

            msg = await self.create_ephemeral_message(
                ephemeral_thread.id, prompt, ephemeral_worker.id
            )
            ephemeral_run = await self.create_ephemeral_run(
                ephemeral_worker.id, ephemeral_thread.id
            )

            yield json.dumps(
                {
                    "type": "activity",
                    "activity": "Worker active. Streaming...",
                    "state": "in_progress",
                    "tool": "delegate_research_task",
                    "run_id": run_id,
                }
            )

            # 5. Configure Stream
            sync_stream = self.project_david_client.synchronous_inference_stream
            sync_stream.setup(
                thread_id=ephemeral_thread.id,
                assistant_id=ephemeral_worker.id,
                message_id=msg.id,
                run_id=ephemeral_run.id,
                api_key=self._delegation_api_key,
            )

            # 6. Stream Execution (Using helper to keep handler clean)
            #    We use the helper to avoid the 'background_stream_worker' def block
            async for event in self._stream_sync_generator(
                sync_stream.stream_events,
                provider="together-ai",
                model="together-ai/Qwen/Qwen3-Coder-480B-A35B-Instruct-FP8",
            ):
                payload = None
                if hasattr(event, "content") and event.content:
                    payload = event.content
                elif hasattr(event, "reasoning") and event.reasoning:
                    payload = event.reasoning
                elif hasattr(event, "text") and event.text:
                    payload = event.text

                if payload:
                    captured_stream_content += payload  # Accumulate locally
                    yield json.dumps({"content": payload, "run_id": run_id})

            # 7. Final Report Gathering
            yield json.dumps(
                {
                    "type": "activity",
                    "activity": "Finalizing worker report...",
                    "state": "in_progress",
                    "tool": "delegate_research_task",
                    "run_id": run_id,
                }
            )

            # Try fetching from DB first
            final_content = await self._fetch_worker_final_report(
                thread_id=ephemeral_thread.id
            )

            # FALLBACK: If DB fetch missed it, use our captured buffer
            if not final_content and captured_stream_content:
                LOG.info("⚠️ [DELEGATE] Using captured stream buffer as final report.")
                final_content = captured_stream_content

            if not final_content:
                final_content = "No report generated by worker."
                execution_had_error = True

            # 8. Submit Output
            await self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                content=final_content,
                action=action,
                is_error=execution_had_error,
            )

            # Update Action Status
            if action:
                status = (
                    StatusEnum.completed.value
                    if not execution_had_error
                    else StatusEnum.failed.value
                )
                await asyncio.to_thread(
                    self.project_david_client.actions.update_action,
                    action_id=action.id,
                    status=status,
                )

        except Exception as e:
            execution_had_error = True
            LOG.error(f"❌ [DELEGATE] Error: {e}", exc_info=True)
            yield json.dumps(
                {
                    "type": "activity",
                    "activity": f"Error: {str(e)}",
                    "state": "error",
                    "tool": "delegate_research_task",
                    "run_id": run_id,
                }
            )

        finally:
            # 9. Cleanup
            if ephemeral_worker:
                await self._ephemeral_clean_up(
                    ephemeral_worker.id,
                    ephemeral_thread.id,
                    self._delete_ephemeral_thread,
                )

            yield json.dumps(
                {
                    "type": "activity",
                    "activity": "Delegation complete.",
                    "state": "completed" if not execution_had_error else "error",
                    "tool": "delegate_research_task",
                    "run_id": run_id,
                }
            )
