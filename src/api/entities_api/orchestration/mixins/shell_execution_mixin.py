from __future__ import annotations

import json
from typing import Any, Dict, Generator, List, Optional

from entities_api.platform_tools.handlers.computer.shell_command_interface import \
    run_shell_commands
from src.api.entities_api.services.logging_service import LoggingUtility

LOG = LoggingUtility()


class ShellExecutionMixin:
    """Executes POSIX‑style shell commands inside the Project‑David sandbox."""

    def handle_shell_action(
        self,
        thread_id: str,
        run_id: str,
        assistant_id: str,
        arguments_dict: Dict[str, Any],
        tool_call_id: Optional[str] = None,
        # [NEW] Accept decision payload
        decision: Optional[Dict] = None,
    ) -> Generator[str, None, None]:
        LOG.info("ShellExecutionMixin: started for run_id=%s", run_id)
        yield json.dumps(
            {
                "stream_type": "computer_execution",
                "chunk": {"type": "status", "status": "started", "run_id": run_id},
            }
        )
        action_tool_name = "computer"

        action = self.project_david_client.actions.create_action(
            tool_name=action_tool_name,
            run_id=run_id,
            tool_call_id=tool_call_id,
            function_args=arguments_dict,
            # [NEW] Pass to API/Service
            decision=decision,
        )

        commands: List[str] = arguments_dict.get("commands", [])
        if not commands:
            no_cmd_msg = "[No shell commands provided to execute.]"
            yield json.dumps({"type": "computer_output", "content": no_cmd_msg})
            self.project_david_client.messages.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
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
        chunk_count = 0
        try:
            for chunk in run_shell_commands(commands, thread_id=thread_id):
                chunk_count += 1
                accumulated_content += chunk
                yield chunk
        except Exception as e_run_shell:
            err_msg = f"Error during shell command execution: {e_run_shell}"
            yield json.dumps(
                {
                    "stream_type": "computer_execution",
                    "chunk": {"type": "error", "content": err_msg},
                }
            )
            self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                content=err_msg,
                action=action,
            )
            return
        if not accumulated_content:
            no_out_msg = "No computer output was generated. The command may have failed silently or produced no output."
            yield json.dumps(
                {
                    "stream_type": "computer_execution",
                    "chunk": {"type": "computer_output", "content": no_out_msg},
                }
            )
            self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                content=no_out_msg,
                action=action,
            )
        else:
            self.submit_tool_output(
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
