from __future__ import annotations

import json
import logging
import os
import time
import traceback
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from httpx import HTTPStatusError
from projectdavid_common.validation import StatusEnum

from entities_api.constants.platform import ERROR_NO_CONTENT
from entities_api.services.logging_service import LoggingUtility

load_dotenv()

LOG = LoggingUtility()
logger = logging.getLogger(__name__)

SURFACE_TRACEBACK = os.getenv("SURFACE_TRACEBACK", "false").lower() == "true"


class ConsumerToolHandlersMixin:
    # ------------------------------------------------------------------ #
    # Core Tool Output Helpers                                           #
    # ------------------------------------------------------------------ #
    def submit_tool_output(
        self,
        *,
        thread_id: str,
        assistant_id: str,
        content: str,
        action: Any,
        is_error: bool = False,
    ) -> None:
        """
        Push tool output (or error) to the thread and update Action status.
        Args:
            is_error: If True, marks the Action as failed and formats content as an error payload.
        """
        if not content:
            content = ERROR_NO_CONTENT

        try:
            # Submit to thread
            self.project_david_client.messages.submit_tool_output(
                thread_id=thread_id,
                content=content,
                role="tool",
                assistant_id=assistant_id,
                tool_id=getattr(action, "id", "dummy"),  # Fallback for tests
            )
            # Update Action status
            self.project_david_client.actions.update_action(
                action_id=action.id,
                status=StatusEnum.failed if is_error else StatusEnum.completed,
            )
        except Exception as exc:
            LOG.error("submit_tool_output failed: %s", exc, exc_info=True)
            self._submit_fallback_error(
                thread_id, assistant_id, f"ERROR: {exc}", action
            )

    def _submit_fallback_error(
        self, thread_id: str, assistant_id: str, error_msg: str, action: Any
    ) -> None:
        """Fallback for critical submit_tool_output failures."""
        try:
            self.project_david_client.messages.submit_tool_output(
                thread_id=thread_id,
                content=error_msg,
                role="tool",
                assistant_id=assistant_id,
                tool_id=getattr(action, "id", "dummy"),
            )
        finally:
            self.project_david_client.actions.update_action(
                action_id=action.id, status=StatusEnum.failed
            )

    # ------------------------------------------------------------------ #
    # Error Formatting & Propagation                                    #
    # ------------------------------------------------------------------ #
    def _format_error_payload(
        self, exc: Exception, include_traceback: bool = False
    ) -> str:
        """Structures errors for user-facing output."""
        error_data = {
            "error_type": exc.__class__.__name__,
            "message": str(exc),
        }
        if isinstance(exc, HTTPStatusError):
            error_data.update(
                {
                    "status_code": exc.response.status_code,
                    "url": str(exc.request.url),
                    "response_text": exc.response.text,
                }
            )
        if include_traceback:
            error_data["traceback"] = traceback.format_exc()
        return json.dumps(error_data, indent=2)

    def _handle_tool_error(
        self,
        exc: Exception,
        *,
        thread_id: str,
        assistant_id: str,
        action: Any,
    ) -> None:
        """Logs, surfaces, and propagates errors."""
        error_payload = self._format_error_payload(exc, SURFACE_TRACEBACK)
        LOG.error(
            "Tool error [action=%s]: %s", action.id, error_payload, exc_info=True
        )
        self.submit_tool_output(
            thread_id=thread_id,
            assistant_id=assistant_id,
            content=error_payload,
            action=action,
            is_error=True,
        )
        raise exc  # Propagate for upstream metrics/retries

    # ------------------------------------------------------------------ #
    # Generic Tool-Call Lifecycle                                        #
    # ------------------------------------------------------------------ #
    def _process_tool_calls(
        self,
        thread_id: str,
        assistant_id: str,
        content: Dict[str, Any],
        run_id: str,
        *,
        api_key: Optional[str] = None,
        poll_interval: float = 1.0,
        max_wait: float = 60.0,
    ) -> None:
        """
        Handles consumer-side tool calls with dual-path error handling.
        """
        action = self.project_david_client.actions.create_action(
            tool_name=content["name"],  # e.g., "code_interpreter"
            run_id=run_id,
            function_args=content["arguments"],
        )

        try:
            # Mark run as pending and wait for external worker
            self.project_david_client.runs.update_run_status(
                run_id, StatusEnum.pending_action
            )
            self._poll_for_completion(run_id, action.id, max_wait, poll_interval)
            LOG.debug("Tool %s dispatched (run %s)", content["name"], run_id)

        except Exception as exc:
            self._handle_tool_error(
                exc,
                thread_id=thread_id,
                assistant_id=assistant_id,
                action=action,
            )

    def _poll_for_completion(
        self, run_id: str, action_id: str, max_wait: float, poll_interval: float
    ) -> None:
        """Polls until the Action is completed or timeout."""
        start = time.time()
        while True:
            if not self.project_david_client.actions.get_pending_actions(run_id=run_id):
                break
            if time.time() - start > max_wait:
                raise TimeoutError(
                    f"Timeout waiting for action {action_id} (run {run_id})"
                )
            time.sleep(poll_interval)

    # ------------------------------------------------------------------ #
    # Conversation Finalization                                          #
    # ------------------------------------------------------------------ #
    def handle_error(
        self, assistant_reply: str, thread_id: str, assistant_id: str, run_id: str
    ) -> None:
        """Saves partial assistant output and marks run as failed."""
        if not assistant_reply:
            return
        self._save_assistant_message(
            thread_id, assistant_id, run_id, assistant_reply, is_error=True
        )

    def finalize_conversation(
        self, assistant_reply: str, thread_id: str, assistant_id: str, run_id: str
    ) -> None:
        """Saves final assistant output and marks run as completed."""
        if not assistant_reply:
            return
        self._save_assistant_message(
            thread_id, assistant_id, run_id, assistant_reply, is_error=False
        )

    def _save_assistant_message(
        self,
        thread_id: str,
        assistant_id: str,
        run_id: str,
        content: str,
        is_error: bool,
    ) -> None:
        """Unified method for saving assistant messages and updating run status."""
        self.project_david_client.messages.save_assistant_message_chunk(
            thread_id=thread_id,
            content=content,
            role="assistant",
            assistant_id=assistant_id,
            sender_id=assistant_id,
            is_last_chunk=True,
        )
        self.project_david_client.runs.update_run_status(
            run_id=run_id,
            new_status=StatusEnum.failed if is_error else StatusEnum.completed,
        )
