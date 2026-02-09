from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

import jwt
from projectdavid_common import ToolValidator

# --- DEPENDENCIES ---
from entities_api.platform_tools.handlers.computer.shell_command_interface import (
    run_shell_commands_async,
)
from src.api.entities_api.services.logging_service import LoggingUtility

LOG = LoggingUtility()


class ShellExecutionMixin:
    """
    Executes POSIX‑style shell commands inside the Project‑David sandbox asynchronously.

    Level 2 Enhancement: Automated self-correction for shell failures (missing binaries,
    path errors, or command syntax issues).
    """

    @staticmethod
    def _format_level2_shell_error(error_content: str) -> str:
        """
        Translates raw shell stderr or execution crashes into actionable hints for the LLM.
        """
        return (
            f"Shell Execution Failed:\n{error_content}\n\n"
            "Instructions: Please analyze the error output above. If a command was 'not found', "
            "verify the binary name or check if it needs to be installed. If a path is incorrect, "
            "list the directory contents first. Correct your commands and retry execution."
        )

        # -------------------------------------------------------------------------
        # FIXED: Renamed method to avoid MRO collision with CodeExecutionMixin
        # -------------------------------------------------------------------------

    def _generate_shell_auth_token(self, subject_id: str, room_id: str) -> str:
        """
        Generates a short-lived JWT to authorize the connection to the Sandbox API.
        Renamed to avoid conflict with other mixins using _generate_sandbox_token.
        """
        secret = os.getenv("SANDBOX_AUTH_SECRET")
        if not secret:
            LOG.error("CRITICAL: SANDBOX_AUTH_SECRET is missing in environment variables.")
            raise ValueError("Server configuration error: Sandbox secret missing.")

        payload = {
            "sub": subject_id,
            "room": room_id,
            "iat": int(time.time()),
            "exp": int(time.time()) + 60,
            "scopes": ["execution", "shell"],
        }

        return jwt.encode(payload, secret, algorithm="HS256")

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
        Signals the internal orchestrator loop for Turn 2 if execution fails.
        """
        LOG.info("ShellExecutionMixin: started for run_id=%s", run_id)

        yield json.dumps(
            {
                "stream_type": "computer_execution",
                "chunk": {"type": "status", "status": "started", "run_id": run_id},
            }
        )

        # --- [L2] SHARED INPUT VALIDATION ---
        validator = ToolValidator()
        validator.schema_registry = {"computer": ["commands"]}

        validation_error = validator.validate_args("computer", arguments_dict)
        is_valid = validation_error is None

        if not is_valid:
            LOG.warning(f"ShellExecution ▸ Validation Failed: {validation_error}")

            try:
                action = await asyncio.to_thread(
                    self.project_david_client.actions.create_action,
                    tool_name="computer",
                    run_id=run_id,
                    tool_call_id=tool_call_id,
                    function_args=arguments_dict,
                    decision=decision,
                )
            except Exception:
                pass

            error_msg = (
                f"{validation_error}\n" "Please correct the function arguments and try again."
            )

            yield json.dumps(
                {
                    "stream_type": "computer_execution",
                    "chunk": {"type": "error", "content": validation_error},
                }
            )

            await self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                content=error_msg,
                action=action if "action" in locals() else None,
                is_error=True,
            )
            return
        # -----------------------------

        # 1. Create Action Record
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
                    "stream_type": "computer_execution",
                    "chunk": {"type": "error", "content": f"Creation failed: {e}"},
                }
            )
            return

        commands: List[str] = arguments_dict.get("commands", [])
        if not commands:
            await self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                content="No commands provided.",
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
        execution_had_error = False

        # 2. Native Async Streaming
        try:
            # -----------------------------------------------------------------
            # FIXED: Pass thread_id as room_id when generating the token
            # -----------------------------------------------------------------
            auth_token = self._generate_shell_auth_token(
                subject_id=f"run_{run_id}", room_id=thread_id  # <--- Pass the thread_id here
            )

            # Pass the token (containing the room claim) to the websocket client
            async for chunk in run_shell_commands_async(
                commands, thread_id=thread_id, token=auth_token
            ):
                accumulated_content += chunk

                if any(
                    err_marker in chunk.lower()
                    for err_marker in [
                        "not found",
                        "permission denied",
                        "error:",
                        "no such file",
                    ]
                ):
                    execution_had_error = True

                yield json.dumps(
                    {
                        "stream_type": "computer_execution",
                        "chunk": {"type": "computer_output", "content": chunk},
                    }
                )

        except Exception as e:
            execution_had_error = True
            err_msg = f"Exception during shell execution: {e}"
            LOG.error(f"ShellExecution ▸ {err_msg}")

            yield json.dumps(
                {
                    "stream_type": "computer_execution",
                    "chunk": {"type": "error", "content": err_msg},
                }
            )

        # 3. Final Summary & Level 2 Correction Logic
        if execution_had_error:
            final_content = self._format_level2_shell_error(
                accumulated_content or "Unknown shell failure."
            )
            LOG.warning(f"ShellExecution ▸ Self-Correction Triggered for run {run_id}")
        else:
            final_content = (
                accumulated_content.strip() or "Command executed successfully with no output."
            )

        # 4. Submit Result
        await self.submit_tool_output(
            thread_id=thread_id,
            assistant_id=assistant_id,
            tool_call_id=tool_call_id,
            content=final_content,
            action=action,
            is_error=execution_had_error,
        )

        yield json.dumps(
            {
                "stream_type": "computer_execution",
                "chunk": {"type": "status", "status": "complete", "run_id": run_id},
            }
        )
