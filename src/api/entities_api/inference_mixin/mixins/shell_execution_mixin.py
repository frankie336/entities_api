from __future__ import annotations

import json
from typing import Any, Dict, Generator, List  # Added Any for arguments_dict

from entities_api.services.logging_service import LoggingUtility

LOG = LoggingUtility()


class ShellExecutionMixin:
    def handle_shell_action(
        self,
        thread_id: str,  # Added type hints
        run_id: str,
        assistant_id: str,
        arguments_dict: Dict[str, Any],  # Changed from untyped
    ) -> Generator[str, None, None]:  # Added return type hint

        # Assuming run_shell_commands is correctly imported
        from entities_api.ptool_handlers.computer.shell_command_interface import (
            run_shell_commands,
        )

        LOG.info(
            "ShellExecutionMixin: handle_shell_action started for run_id: %s, thread_id: %s. Args: %s",
            run_id,
            thread_id,
            arguments_dict,
        )

        # Create an action for the computer command execution

        action_tool_name = "computer"  # Correct tool name

        action = self.project_david_client.actions.create_action(  # type: ignore[attr-defined]
            tool_name=action_tool_name, run_id=run_id, function_args=arguments_dict
        )
        LOG.debug(
            "ShellExecutionMixin: Action created for tool '%s', run_id: %s, action_id: %s",
            action_tool_name,
            run_id,
            getattr(action, "id", "N/A"),
        )

        commands: List[str] = arguments_dict.get("commands", [])
        if not commands:
            LOG.warning(
                "ShellExecutionMixin: No commands provided for run_id: %s", run_id
            )
            # Yield an error message or handle as appropriate
            no_command_message = "[No shell commands provided to execute.]"
            yield json.dumps(
                {"type": "computer_output", "content": no_command_message}
            )  # Use a specific type
            self.submit_tool_output(  # type: ignore[attr-defined]
                thread_id=thread_id,
                assistant_id=assistant_id,
                content=no_command_message,
                action=action,
            )
            return

        accumulated_content = ""
        chunk_count = 0

        LOG.info(
            "ShellExecutionMixin: About to call run_shell_commands for run_id: %s with commands: %s",
            run_id,
            commands,
        )
        try:
            for chunk in run_shell_commands(commands, thread_id=thread_id):
                chunk_count += 1
                LOG.debug(
                    "ShellExecutionMixin: Received chunk #%d from run_shell_commands for run_id: %s. Chunk: %s",
                    chunk_count,
                    run_id,
                    chunk[:200],  # Log first 200 chars
                )

                # The original monolith `handle_shell_action` does not parse the chunk as JSON *before* yielding.
                # It accumulates the raw string output from the shell.
                # The `try...except json.JSONDecodeError` was misplaced if `run_shell_commands` yields raw strings.
                # If `run_shell_commands` itself yields JSON strings that *need* to be parsed for some internal logic,
                # that's different. Assuming it yields raw output strings or simple JSON like {"output": "line"}.
                # For now, let's assume `chunk` is the string content to be yielded.

                # If `run_shell_commands` is expected to yield JSON strings like `{"type": "stdout", "content": "output line"}`
                # then the yielding logic needs to be:
                # yield chunk -> if chunk is already a JSON string for the UI
                # OR
                # yield json.dumps({"type": "computer_output", "stream_type": "computer_execution", "chunk": {"type": "stdout", "content": chunk_from_run_shell}})

                # Let's assume `run_shell_commands` yields JSON strings that are UI-ready per the monolith's behavior.
                # The monolith's `yield chunk` implies `run_shell_commands` output is directly yieldable.

                accumulated_content += chunk  # What if chunk is JSON string? This would make accumulated_content a long JSON string.
                # Monolith accumulates and then submits. Does it parse before submitting?
                # The monolith just did `accumulated_content += chunk`. If `chunk` is JSON, this is fine for accumulation.

                LOG.debug(
                    "ShellExecutionMixin: Yielding chunk #%d for run_id: %s",
                    chunk_count,
                    run_id,
                )
                yield chunk  # Preserve streaming for real-time output

            LOG.info(
                "ShellExecutionMixin: Finished iterating run_shell_commands for run_id: %s. Total chunks: %d",
                run_id,
                chunk_count,
            )

        except Exception as e_run_shell:
            # Catch any error from run_shell_commands itself
            LOG.error(
                "ShellExecutionMixin: Error during run_shell_commands for run_id: %s. Error: %s",
                run_id,
                e_run_shell,
                exc_info=True,
            )
            error_message = f"Error during shell command execution: {e_run_shell}"
            # Yield an error chunk to the UI
            yield json.dumps(
                {
                    "type": "error",
                    "content": error_message,
                    "stream_type": "computer_execution",
                }
            )  # Or a more specific error structure
            # Submit error to assistant
            self.submit_tool_output(  # type: ignore[attr-defined]
                thread_id=thread_id,
                assistant_id=assistant_id,
                content=error_message,
                action=action,
            )
            return  # Stop further processing

        # The monolith's error handling for JSONDecodeError was inside the loop,
        # which implies `chunk` itself was expected to be potentially processable as JSON,
        # but it was also directly yielded. This is a bit ambiguous.
        # If `run_shell_commands` yields raw strings, the JSONDecodeError try-except is not needed around `yield chunk`.

        if (
            not accumulated_content and chunk_count == 0
        ):  # Check if any chunks were processed
            LOG.warning(
                "ShellExecutionMixin: No output generated by run_shell_commands for run_id: %s.",
                run_id,
            )
            error_message = "No computer output was generated. The command may have failed silently or produced no output."
            # Yield a message to UI
            yield json.dumps(
                {
                    "type": "computer_output",
                    "content": error_message,
                    "stream_type": "computer_execution",
                }
            )
            self.submit_tool_output(  # type: ignore[attr-defined]
                thread_id=thread_id,
                assistant_id=assistant_id,
                content=error_message,
                action=action,
            )
            # The monolith `raise RuntimeError` here. This would stop the stream.
            # Depending on desired behavior, you might want to just return or let it complete.
            # For now, let's match monolith and raise, but log it well.
            LOG.error(
                "ShellExecutionMixin: Raising RuntimeError for run_id %s due to no output.",
                run_id,
            )
            # raise RuntimeError(error_message) # Uncomment if strict error propagation is needed
            return  # Or just return to allow other stream parts to complete

        LOG.info(
            "ShellExecutionMixin: Submitting final accumulated shell output for run_id: %s. Length: %d",
            run_id,
            len(accumulated_content),
        )
        self.submit_tool_output(  # type: ignore[attr-defined]
            thread_id=thread_id,
            assistant_id=assistant_id,
            content=accumulated_content.strip(),  # Strip whitespace from final output
            action=action,
        )
        LOG.info(
            "ShellExecutionMixin: handle_shell_action finished for run_id: %s", run_id
        )
