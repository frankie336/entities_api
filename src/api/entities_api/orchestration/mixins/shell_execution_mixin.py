from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncGenerator, Dict, List, Optional

# --- DEPENDENCIES ---
from entities_api.platform_tools.handlers.computer.shell_command_interface import \
    run_shell_commands
from src.api.entities_api.services.logging_service import LoggingUtility

LOG = LoggingUtility()


class ShellExecutionMixin:
    """Executes POSIX‑style shell commands inside the Project‑David sandbox asynchronously."""

    async def handle_shell_action(
        self,
        thread_id: str,
        run_id: str,
        assistant_id: str,
        arguments_dict: Dict[str, Any],
        tool_call_id: Optional[str] = None,
        decision: Optional[Dict] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Asynchronous handler for shell commands.
        Offloads blocking execution to threads to keep the event loop responsive.
        """
        LOG.info("ShellExecutionMixin: started for run_id=%s", run_id)

        yield json.dumps(
            {
                "stream_type": "computer_execution",
                "chunk": {"type": "status", "status": "started", "run_id": run_id},
            }
        )

        # 1. Create Action Record (Offloaded to thread with keyword safety)
        try:
            action = await asyncio.to_thread(
                self.project_david_client.actions.create_action,
                tool_name="computer",
                run_id=run_id,
                tool_call_id=tool_call_id,
                function_args=arguments_dict,
                decision=decision,
            )
        except Exception as e:
            LOG.error(f"ShellExecution ▸ Action creation failed: {e}")
            yield json.dumps(
                {
                    "type": "error",
                    "chunk": {"type": "error", "content": f"Creation failed: {e}"},
                }
            )
            return

        commands: List[str] = arguments_dict.get("commands", [])

        # 2. Handle Empty Commands
        if not commands:
            no_cmd_msg = "[No shell commands provided to execute.]"
            yield json.dumps(
                {
                    "stream_type": "computer_execution",
                    "chunk": {"type": "computer_output", "content": no_cmd_msg},
                }
            )
            # Await the async submission
            await self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                content=no_cmd_msg,
                action=action,
            )
            yield json.dumps(
                {
                    "stream_type": "computer_execution",
                    "chunk": {"type": "status", "status": "complete", "run_id": run_id},
                }
            )
            return

        accumulated_content = ""

        # 3. Stream Shell Execution (Non-blocking iteration)
        try:
            # run_shell_commands is a sync generator; iterate it via thread offloading
            sync_iter = iter(run_shell_commands(commands, thread_id=thread_id))

            # Re-using our safe_next pattern to prevent StopIteration interaction issues
            def safe_next(it):
                try:
                    return next(it)
                except (StopIteration, Exception):
                    return None

            while True:
                # Offload the blocking wait for shell output to a thread
                chunk = await asyncio.to_thread(safe_next, sync_iter)

                if chunk is None:
                    break

                accumulated_content += chunk
                yield chunk

        except Exception as e_run_shell:
            err_msg = f"Error during shell command execution: {e_run_shell}"
            LOG.error(f"ShellExecution ▸ {err_msg}")
            yield json.dumps(
                {
                    "stream_type": "computer_execution",
                    "chunk": {"type": "error", "content": err_msg},
                }
            )
            await self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                content=err_msg,
                action=action,
                is_error=True,
            )
            return

        # 4. Final Submission
        if not accumulated_content:
            no_out_msg = "No computer output was generated. The command may have produced no output."
            await self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                content=no_out_msg,
                action=action,
            )
        else:
            await self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                content=accumulated_content.strip(),
                action=action,
            )

        yield json.dumps(
            {
                "stream_type": "computer_execution",
                "chunk": {"type": "status", "status": "complete", "run_id": run_id},
            }
        )
        LOG.info("ShellExecutionMixin: finished for run_id=%s", run_id)
