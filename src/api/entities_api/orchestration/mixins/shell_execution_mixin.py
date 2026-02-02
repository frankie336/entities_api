from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncGenerator, Dict, List, Optional

# --- DEPENDENCIES ---
# Import the NEW async version we just created above
from entities_api.platform_tools.handlers.computer.shell_command_interface import \
    run_shell_commands_async
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
        Uses native await to prevent 'asyncio.run' loop conflicts.
        """
        LOG.info("ShellExecutionMixin: started for run_id=%s", run_id)

        yield json.dumps({
            "stream_type": "computer_execution",
            "chunk": {"type": "status", "status": "started", "run_id": run_id},
        })

        # 1. Create Action Record
        try:
            action = await asyncio.to_thread(
                self.project_david_client.actions.create_action,
                tool_name="computer",
                run_id=run_id,
                tool_call_id=tool_call_id,
                function_args=arguments_dict,
                decision=decision, # Corrected to 'decision'
            )
        except Exception as e:
            LOG.error(f"ShellExecution ▸ Action creation failed: {e}")
            yield json.dumps({
                "stream_type": "computer_execution",
                "chunk": {"type": "error", "content": f"Creation failed: {e}"},
            })
            return

        commands: List[str] = arguments_dict.get("commands", [])
        if not commands:
            await self.submit_tool_output(thread_id=thread_id, assistant_id=assistant_id, tool_call_id=tool_call_id, content="No commands provided.", action=action)
            yield json.dumps({"stream_type": "computer_execution", "chunk": {"type": "status", "status": "complete", "run_id": run_id}})
            return

        accumulated_content = ""

        # 2. Native Async Streaming (NO asyncio.run loop conflicts)
        try:
            # We use 'async for' to pull chunks from the WebSocket interface
            async for chunk in run_shell_commands_async(commands, thread_id=thread_id):
                accumulated_content += chunk

                # Wrap output for the normalizer
                yield json.dumps({
                    "stream_type": "computer_execution",
                    "chunk": {"type": "computer_output", "content": chunk},
                })

        except Exception as e:
            err_msg = f"Error during shell execution: {e}"
            LOG.error(f"ShellExecution ▸ {err_msg}")
            yield json.dumps({"stream_type": "computer_execution", "chunk": {"type": "error", "content": err_msg}})
            await self.submit_tool_output(thread_id=thread_id, assistant_id=assistant_id, tool_call_id=tool_call_id, content=err_msg, action=action, is_error=True)
            return

        # 3. Final Submission (Awaiting async submit)
        await self.submit_tool_output(
            thread_id=thread_id,
            assistant_id=assistant_id,
            tool_call_id=tool_call_id,
            content=accumulated_content.strip() or "Command executed with no output.",
            action=action,
        )

        yield json.dumps({
            "stream_type": "computer_execution",
            "chunk": {"type": "status", "status": "complete", "run_id": run_id},
        })
