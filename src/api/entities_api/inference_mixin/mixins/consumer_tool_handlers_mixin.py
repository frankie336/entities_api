"""
Everything related to *consumer-side* (i.e. non-platform) tool calls:

• generic `_process_tool_calls` with polling / timeout
• common helper `submit_tool_output`
• error / finalisation utilities
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict

from projectdavid_common import ValidationInterface

from entities_api.constants.platform import ERROR_NO_CONTENT
from entities_api.services.logging_service import LoggingUtility

LOG = LoggingUtility()
logger = logging.getLogger(__name__)


class ConsumerToolHandlersMixin:
    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #
    def submit_tool_output(
        self,
        *,
        thread_id: str,
        assistant_id: str,
        content: str,
        action,
    ):
        """
        Push the final content into the thread and flip the Action to *completed*.
        Falls back to an “ERROR: …” message and `failed` status if anything blows up.
        """
        if not content:
            content = ERROR_NO_CONTENT

        try:
            self.project_david_client.messages.submit_tool_output(  # type: ignore[attr-defined]
                thread_id=thread_id,
                content=content,
                role="tool",
                assistant_id=assistant_id,
                tool_id="dummy",  # TODO: real id once we expose it
            )
            self.project_david_client.actions.update_action(action_id=action.id, status="completed")  # type: ignore
        except Exception as exc:
            LOG.error("submit_tool_output failed: %s", exc, exc_info=True)
            try:
                self.project_david_client.messages.submit_tool_output(  # type: ignore[attr-defined]
                    thread_id=thread_id,
                    content=f"ERROR: {exc}",
                    role="tool",
                    assistant_id=assistant_id,
                    tool_id="dummy",
                )
            finally:
                self.project_david_client.actions.update_action(action_id=action.id, status="failed")  # type: ignore

    # ------------------------------------------------------------------ #
    # Generic tool-call lifecycle                                        #
    # ------------------------------------------------------------------ #
    def _process_tool_calls(
        self,
        thread_id: str,
        assistant_id: str,
        content: Dict[str, Any],
        run_id: str,
        *,
        api_key: str | None = None,
        poll_interval: float = 1.0,
        max_wait: float = 60.0,
    ):
        """
        Used for *consumer* tools (and “special-case” platform ones).

        Strategy
        --------
        1. create Action row
        2. flip Run → pending_action
        3. wait until some *external worker* finishes the Action OR timeout
        """
        action = self.project_david_client.actions.create_action(
            tool_name="code_interpreter",
            run_id=run_id,
            function_args=content["arguments"],
        )

        runs_client = self.project_david_client.runs  # type: ignore[attr-defined]

        runs_client.update_run_status(
            run_id, ValidationInterface.StatusEnum.pending_action.value
        )

        start = time.time()
        while True:
            if not self.action_client.get_pending_actions(run_id):  # type: ignore
                break
            if time.time() - start > max_wait:
                LOG.warning(
                    "Timeout waiting for action %s on run %s", action.id, run_id
                )
                break
            time.sleep(poll_interval)

        # Nothing else to do here – a separate worker will have called
        # `submit_tool_output` when the task completed.
        LOG.debug("Consumer-tool %s dispatched (run %s)", content["name"], run_id)

    # ------------------------------------------------------------------ #
    # Error / finalisation helpers                                       #
    # ------------------------------------------------------------------ #
    def handle_error(
        self, assistant_reply: str, thread_id: str, assistant_id: str, run_id: str
    ):
        """
        Write partial assistant text, mark run → failed.
        """
        if not assistant_reply:
            return
        self.project_david_client.messages.save_assistant_message_chunk(  # type: ignore[attr-defined]
            thread_id=thread_id,
            content=assistant_reply,
            role="assistant",
            assistant_id=assistant_id,
            sender_id=assistant_id,
            is_last_chunk=True,
        )
        self.project_david_client.runs.update_run_status(  # type: ignore[attr-defined]
            run_id, ValidationInterface.StatusEnum.failed
        )

    def finalize_conversation(
        self, assistant_reply: str, thread_id: str, assistant_id: str, run_id: str
    ):
        """
        Persist the *final* assistant chunk and mark run → completed.
        """
        if not assistant_reply:
            return
        self.project_david_client.messages.save_assistant_message_chunk(  # type: ignore[attr-defined]
            thread_id=thread_id,
            content=assistant_reply,
            role="assistant",
            assistant_id=assistant_id,
            sender_id=assistant_id,
            is_last_chunk=True,
        )
        self.project_david_client.runs.update_run_status(  # type: ignore[attr-defined]
            run_id, ValidationInterface.StatusEnum.completed
        )
