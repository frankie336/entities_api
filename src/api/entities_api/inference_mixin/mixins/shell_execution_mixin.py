"""
Mixin that executes a *remote shell* command list via the dedicated
`computer` tool handler.

This is intentionally kept in a separate module because CI images used
for unit-tests often cannot spawn shells.
"""

from __future__ import annotations

import json
from typing import Dict, Generator, List

from entities_api.services.logging_service import LoggingUtility

LOG = LoggingUtility()


class ShellExecutionMixin:
    # ------------------------------------------------------------------ #
    def handle_shell_action(
        self,
        *,
        thread_id: str,
        run_id: str,
        assistant_id: str,
        arguments_dict: Dict[str, List[str]],
    ) -> Generator[str, None, None]:
        """
        Streams the stdout / stderr of *each* command back to the client.
        Falls back to “ERROR:” chunks on any exception.
        """
        from entities_api.ptool_handlers.computer.shell_command_interface import \
            run_shell_commands

        from .consumer_tool_handlers_mixin import ConsumerToolHandlersMixin

        if not isinstance(self, ConsumerToolHandlersMixin):  # type: ignore
            raise TypeError("ShellExecutionMixin requires ConsumerToolHandlersMixin")

        action = self.action_client.create_action(  # type: ignore
            tool_name="computer",
            run_id=run_id,
            function_args=arguments_dict,
        )

        cmds = arguments_dict.get("commands", [])
        accumulated = ""

        try:
            for chunk in run_shell_commands(cmds, thread_id=thread_id):
                accumulated += chunk
                yield chunk
        except Exception as exc:
            LOG.error("Shell streaming error: %s", exc, exc_info=True)
            err_payload = json.dumps(
                {"type": "error", "content": f"Shell error: {exc}"}
            )
            yield err_payload
            self.submit_tool_output(  # type: ignore[attr-defined]
                thread_id=thread_id,
                assistant_id=assistant_id,
                content=f"ERROR: {exc}",
                action=action,
            )
            return

        if not accumulated:
            accumulated = "[No output produced.]"

        self.submit_tool_output(  # type: ignore[attr-defined]
            thread_id=thread_id,
            assistant_id=assistant_id,
            content=accumulated,
            action=action,
        )
