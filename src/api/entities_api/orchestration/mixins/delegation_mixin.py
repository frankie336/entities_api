from __future__ import annotations

import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from src.api.entities_api.clients.delta_normalizer import DeltaNormalizer
from src.api.entities_api.constants.worker import WORKER_TOOLS

LOG = LoggingUtility()


class DelegationMixin:
    """
    Spins up an ephemeral Worker Loop using the project_david_client strictly.
    Lifecycle matches the central Orchestrator stream logic.
    """

    @asynccontextmanager
    async def _capture_tool_outputs(self, capture_dict: Dict[str, str]):
        """
        Monkey-patches submit_tool_output to notify the local loop
        when a tool result has been committed to the DB.
        """
        original_submit = self.submit_tool_output

        async def intercept_submit(
            thread_id, assistant_id, tool_call_id, content, action=None, is_error=False, **kwargs
        ):
            capture_dict[tool_call_id] = str(content)
            await original_submit(
                thread_id, assistant_id, tool_call_id, content, action, is_error, **kwargs
            )

        self.submit_tool_output = intercept_submit
        try:
            yield
        finally:
            self.submit_tool_output = original_submit

    async def _run_worker_loop(
        self, task: str, requirements: str, run_id: str, parent_thread_id: str
    ) -> str:
        """
        Standard Level 3 lifecycle for the Research Worker.
        """
        model = "Qwen/Qwen2.5-72B-Instruct-Turbo"

        # 1. Spawn Worker (Strict Client Call)
        # Fix for potential WORKER_TOOLS tuple errors
        sanitized_tools = [t[0] if isinstance(t, tuple) else t for t in WORKER_TOOLS]

        try:
            ephemeral_worker = await asyncio.to_thread(
                self.project_david_client.assistants.create,
                name=f"research_worker_{uuid.uuid4().hex[:4]}",
                model=model,
                tools=sanitized_tools,
            )
        except Exception as e:
            return f"Failed to spawn worker via client: {e}"

        # 2. Setup Thread (Strict Client Call)
        try:
            child_thread = await asyncio.to_thread(
                self.project_david_client.threads.create,
                meta_data={"parent_thread_id": parent_thread_id},
            )
        except Exception as e:
            return f"Failed to create research thread: {e}"

        # 3. Initial Message
        await asyncio.to_thread(
            self.project_david_client.messages.create_message,
            thread_id=child_thread.id,
            role="user",
            content=f"TASK: {task}\nREQUIREMENTS: {requirements}",
        )

        client = self._get_client_instance(api_key=os.environ.get("TOGETHER_API_KEY"))

        for turn in range(20):
            # --- TURN START: SYNC CONTEXT FROM DB (Hygiene) ---
            ctx = await self._set_up_context_window(
                assistant_id=ephemeral_worker.id,
                thread_id=child_thread.id,
                trunk=True,
                force_refresh=True,  # Forces hydration from the client/DB
                research_worker=True,
            )

            accumulated, assistant_reply, current_block = "", "", None

            # --- A. INFERENCE ---
            try:
                raw_stream = client.stream_chat_completion(
                    model=model,
                    messages=ctx,
                    tool_choice="auto",
                    max_tokens=4096,
                    temperature=0.3,
                )

                async for chunk in DeltaNormalizer.async_iter_deltas(raw_stream, run_id):
                    ctype, ccontent = chunk.get("type"), chunk.get("content") or ""
                    if ctype == "content":
                        if current_block in ["fc", "think", "plan"]:
                            accumulated += f"</{current_block}>"
                        current_block = None
                        assistant_reply += ccontent
                        accumulated += ccontent
                    elif ctype == "call_arguments":
                        if current_block != "fc":
                            if current_block:
                                accumulated += f"</{current_block}>"
                            accumulated += "<fc>"
                            current_block = "fc"
                        accumulated += ccontent
                    # DeltaNormalizer handles think/plan blocks
            except Exception as e:
                return f"Worker LLM Error: {e}"

            if current_block:
                accumulated += f"</{current_block}>"

            # --- B. PARSE LIFECYCLE (Copy from stream) ---
            tool_calls_batch = self.parse_and_set_function_calls(accumulated, assistant_reply)

            message_to_save = assistant_reply
            if tool_calls_batch:
                # Build Structured Envelope
                tool_calls_structure = []
                for tool in tool_calls_batch:
                    t_id = tool.get("id") or f"call_{uuid.uuid4().hex[:8]}"
                    tool_calls_structure.append(
                        {
                            "id": t_id,
                            "type": "function",
                            "function": {
                                "name": tool.get("name"),
                                "arguments": json.dumps(tool.get("arguments", {})),
                            },
                        }
                    )
                message_to_save = json.dumps(tool_calls_structure)

            # Persist Assistant turn to DB (Strict Client Call)
            await asyncio.to_thread(
                self.project_david_client.messages.create_message,
                thread_id=child_thread.id,
                role="assistant",
                content=message_to_save,
            )

            # --- C. EXIT OR DISPATCH ---
            if not tool_calls_batch:
                return assistant_reply

            # Tool Execution (Mixins handle their own DB updates)
            captured_results: Dict[str, str] = {}
            async with self._capture_tool_outputs(captured_results):
                async for _ in self.process_tool_calls(
                    thread_id=child_thread.id,
                    run_id=run_id,
                    assistant_id=ephemeral_worker.id,
                    tool_call_id=None,
                    decision=None,
                ):
                    pass  # We just wait for the results to be captured

        return "Worker research depth limit reached (20 turns)."

    async def handle_delegate_research_task(
        self, thread_id, run_id, assistant_id, arguments_dict, tool_call_id, decision
    ) -> AsyncGenerator[str, None]:
        """
        Supervisor tool handler for delegation.
        """
        # Yield JSON status for SDK compatibility
        yield json.dumps(
            {
                "type": "status",
                "status": "Spawning research worker...",
                "state": "in_progress",
                "run_id": run_id,
            }
        )

        # Track delegation action
        action = await asyncio.to_thread(
            self.project_david_client.actions.create_action,  # Standard client method
            tool_name="delegate_research_task",
            run_id=run_id,
            tool_call_id=tool_call_id,
            function_args=arguments_dict,
            decision=decision,
        )

        final_output = await self._run_worker_loop(
            arguments_dict.get("task"), arguments_dict.get("requirements", ""), run_id, thread_id
        )

        yield json.dumps(
            {"type": "status", "status": "Research complete.", "state": "success", "run_id": run_id}
        )

        # Finalize Delegation Action
        await asyncio.to_thread(
            self.project_david_client.actions.update_action,
            action_id=action.id,
            status=StatusEnum.completed.value,
        )

        # Return Worker report to the Supervisor
        await self.submit_tool_output(
            thread_id=thread_id,
            assistant_id=assistant_id,
            tool_call_id=tool_call_id,
            content=final_output,
            action=action,
        )
