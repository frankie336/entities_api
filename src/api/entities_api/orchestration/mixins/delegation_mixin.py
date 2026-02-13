from __future__ import annotations

import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Dict

from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from src.api.entities_api.constants.worker import WORKER_TOOLS

LOG = LoggingUtility()


class DelegationMixin:
    """
    Spins up an ephemeral Worker Loop using the project_david_client strictly.
    Lifecycle matches the central Orchestrator stream logic.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._delegation_api_key = None

    @asynccontextmanager
    async def _capture_tool_outputs(self, capture_dict: Dict[str, str]):
        """
        Monkey-patches submit_tool_output to notify the local loop
        when a tool result has been committed to the DB.
        """
        original_submit = self.submit_tool_output

        async def intercept_submit(
            thread_id,
            assistant_id,
            tool_call_id,
            content,
            action=None,
            is_error=False,
            **kwargs,
        ):
            capture_dict[tool_call_id] = str(content)
            await original_submit(
                thread_id,
                assistant_id,
                tool_call_id,
                content,
                action,
                is_error,
                **kwargs,
            )

        self.submit_tool_output = intercept_submit
        try:
            yield
        finally:
            self.submit_tool_output = original_submit

    async def _run_worker_loop(
        self, task: str, requirements: str, run_id: str, parent_thread_id: str
    ) -> str:
        LOG.info(
            f"🛑 DELEGATION STUB: Received task '{task}' from thread {parent_thread_id}"
        )
        return f"Delegation Acknowledged. Task: {task}. Requirements: {requirements}"

    async def create_ephemeral_worker_assistant(self):

        ephemeral_worker = await asyncio.to_thread(
            self.project_david_client.assistants.create_assistant,
            name=f"worker_{uuid.uuid4().hex[:8]}",
            description="Temp assistant for deep research",
            tools=WORKER_TOOLS,
            deep_research=False,
        )
        return ephemeral_worker

    async def create_ephemeral_thread(self):

        ephemeral_thread = await asyncio.to_thread(
            self.project_david_client.threads.create_thread
        )
        return ephemeral_thread

    async def create_ephemeral_message(
        self,
        thread_id: str,
        content: str,
        assistant_id: str,
    ):
        ephemeral_message = await asyncio.to_thread(
            self.project_david_client.messages.create_message,
            thread_id=thread_id,
            assistant_id=assistant_id,
            content=content,
        )
        return ephemeral_message

    async def create_ephemeral_run(self, assistant_id: str, thread_id: str):

        ephemeral_run = await asyncio.to_thread(
            self.project_david_client.runs.create_run,
            assistant_id=assistant_id,
            thread_id=thread_id,
        )
        return ephemeral_run

    async def _fetch_ephemeral_result(
        self, thread_id: str, assistant_id: str
    ) -> str | None:
        """
        Retrieves the final text response from the ephemeral thread using the SDK.
        """
        LOG.info(
            f"🔍 [FETCH-RESULT] Starting fetch for Thread: {thread_id} | Assistant: {assistant_id}"
        )
        try:
            envelope = await asyncio.to_thread(
                self.project_david_client.messages.list_messages,
                thread_id=thread_id,
                limit=5,
                order="desc",
            )

            if not envelope or not envelope.data:
                return None

            for msg in envelope.data:
                if msg.role == "assistant" and msg.assistant_id == assistant_id:
                    content_text = ""
                    if hasattr(msg, "content") and isinstance(msg.content, list):
                        for block in msg.content:
                            if getattr(block, "type", "") == "text":
                                content_text += block.text.value
                    elif hasattr(msg, "content") and isinstance(msg.content, str):
                        content_text = msg.content

                    if content_text:
                        return content_text
            return None
        except Exception as e:
            LOG.error(f"❌ [FETCH-RESULT] Exception: {e}", exc_info=True)
            return None

    async def handle_delegate_research_task(
        self, thread_id, run_id, assistant_id, arguments_dict, tool_call_id, decision
    ) -> AsyncGenerator[str, None]:
        """
        Supervisor tool handler for delegation.
        """
        LOG.info(f"🔄 [DELEGATE] STARTING. Run: {run_id} | ToolCall: {tool_call_id}")

        from projectdavid.events import ContentEvent, ReasoningEvent

        yield json.dumps(
            {
                "type": "status",
                "status": "Initializing delegation action...",
                "state": "in_progress",
                "run_id": run_id,
            }
        )

        # --- [CRITICAL FIX] PARSE & FORMAT ARGUMENTS ---
        # Ensure we have a dict, even if the model passed a stringified JSON
        if isinstance(arguments_dict, str):
            try:
                args = json.loads(arguments_dict)
            except:
                args = {"task": arguments_dict}  # Fallback if raw string
        else:
            args = arguments_dict

        # Extract fields
        task_text = args.get("task", "No specific task description provided.")
        requirements_text = args.get("requirements", "No specific constraints.")
        context_text = args.get("context", "")

        # Create a clean, human-readable prompt for the worker
        # This prevents "JSON confusion" and ensures requirements aren't ignored.
        formatted_handoff_prompt = (
            f"### 📋 Research Assignment\n\n"
            f"**Task:**\n{task_text}\n\n"
            f"**Requirements & Constraints:**\n{requirements_text}\n"
        )

        if context_text:
            formatted_handoff_prompt += f"\n**Additional Context:**\n{context_text}\n"

        # =========================================================================
        # 0. CREATE ACTION RECORD (DB)
        # =========================================================================
        action = None
        try:
            # We save the RAW dict to DB for auditing
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

        # =========================================================================
        # 1. SETUP EPHEMERAL ENVIRONMENT
        # =========================================================================
        try:
            yield json.dumps(
                {
                    "type": "status",
                    "status": "Spawning ephemeral research assistant...",
                    "state": "in_progress",
                    "run_id": run_id,
                }
            )
            ephemeral_worker = await self.create_ephemeral_worker_assistant()

            yield json.dumps(
                {
                    "type": "status",
                    "status": "Preparing secure research thread...",
                    "state": "in_progress",
                    "run_id": run_id,
                }
            )
            ephemeral_thread = await self.create_ephemeral_thread()

            yield json.dumps(
                {
                    "type": "status",
                    "status": "Transmitting task context...",
                    "state": "in_progress",
                    "run_id": run_id,
                }
            )

            # [FIX] Send the formatted prompt, not just the task key
            ephemeral_message = await self.create_ephemeral_message(
                thread_id=ephemeral_thread.id,
                assistant_id=ephemeral_worker.id,
                content=formatted_handoff_prompt,
            )

            yield json.dumps(
                {
                    "type": "status",
                    "status": "Starting execution loop...",
                    "state": "in_progress",
                    "run_id": run_id,
                }
            )
            ephemeral_run = await self.create_ephemeral_run(
                assistant_id=ephemeral_worker.id, thread_id=ephemeral_thread.id
            )
            LOG.info(f"🔄 [DELEGATE] Ephemeral Run Ready: {ephemeral_run.id}")

        except Exception as e:
            LOG.error(f"❌ [DELEGATE] Setup Phase Failed: {e}", exc_info=True)
            yield json.dumps(
                {
                    "type": "status",
                    "status": f"Setup failed: {str(e)}",
                    "state": "error",
                    "run_id": run_id,
                }
            )
            return

        # =========================================================================
        # 2. CONFIGURE & EXECUTE STREAM
        # =========================================================================
        yield json.dumps(
            {
                "type": "status",
                "status": "Sub-worker active. Streaming insights...",
                "state": "in_progress",
                "run_id": run_id,
            }
        )

        sync_stream = self.project_david_client.synchronous_inference_stream
        sync_stream.setup(
            thread_id=ephemeral_thread.id,
            assistant_id=ephemeral_worker.id,
            message_id=ephemeral_message.id,
            run_id=ephemeral_run.id,
            api_key=self._delegation_api_key,
        )

        event_queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        execution_had_error = False
        error_message = None

        def background_stream_worker():
            try:
                # [NOTE] Ensure this model string matches your config
                for event in sync_stream.stream_events(
                    provider="together-ai",
                    model="together-ai/deepseek-ai/DeepSeek-R1",
                ):
                    loop.call_soon_threadsafe(event_queue.put_nowait, event)
            except Exception as e:
                loop.call_soon_threadsafe(event_queue.put_nowait, e)
            finally:
                loop.call_soon_threadsafe(event_queue.put_nowait, None)

        asyncio.create_task(asyncio.to_thread(background_stream_worker))

        try:
            while True:
                event = await event_queue.get()
                if event is None:
                    break
                if isinstance(event, Exception):
                    raise event

                if isinstance(event, ContentEvent):
                    yield json.dumps(
                        {"type": "content", "content": event.content, "run_id": run_id}
                    )
                elif isinstance(event, ReasoningEvent):
                    yield json.dumps(
                        {
                            "type": "reasoning",
                            "content": event.content,
                            "run_id": run_id,
                        }
                    )

        except Exception as e:
            execution_had_error = True
            error_message = str(e)
            LOG.error(f"❌ [DELEGATE] Stream execution failed: {e}", exc_info=True)
            yield json.dumps(
                {
                    "type": "status",
                    "status": f"Worker error: {error_message}",
                    "state": "error",
                    "run_id": run_id,
                }
            )

        # =========================================================================
        # 3. FETCH RESULT & CLOSE LOOP
        # =========================================================================
        yield json.dumps(
            {
                "type": "status",
                "status": "Collecting final report...",
                "state": "in_progress",
                "run_id": run_id,
            }
        )

        final_content = await self._fetch_ephemeral_result(
            thread_id=ephemeral_thread.id, assistant_id=ephemeral_worker.id
        )

        if not final_content:
            final_content = (
                f"Delegation error: {error_message}"
                if execution_had_error
                else "No report generated."
            )

        try:
            yield json.dumps(
                {
                    "type": "status",
                    "status": "Submitting report...",
                    "state": "in_progress",
                    "run_id": run_id,
                }
            )

            await self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                content=final_content,
                action=action,
                is_error=execution_had_error,
            )

            if action:
                await asyncio.to_thread(
                    self.project_david_client.actions.update_action,
                    action_id=action.id,
                    status=(
                        StatusEnum.completed.value
                        if not execution_had_error
                        else StatusEnum.failed.value
                    ),
                )
            LOG.info("✅ [DELEGATE] Tool Output Submitted.")
        except Exception as e:
            LOG.error(f"❌ [DELEGATE] Submission failure: {e}")

        yield json.dumps(
            {
                "type": "status",
                "status": "Delegation complete.",
                "state": "completed" if not execution_had_error else "error",
                "run_id": run_id,
            }
        )
