# src/api/entities_api/orchestration/mixins/consumer_tool_handlers_mixin.py
from __future__ import annotations

import json
import logging
import os
import time
import traceback
from typing import Any, Dict, Generator, Optional

from dotenv import load_dotenv
from httpx import HTTPStatusError
from projectdavid_common.validation import StatusEnum

from src.api.entities_api.constants.platform import ERROR_NO_CONTENT
from src.api.entities_api.services.logging_service import LoggingUtility

load_dotenv()
LOG = LoggingUtility()
logger = logging.getLogger(__name__)
SURFACE_TRACEBACK = os.getenv("SURFACE_TRACEBACK", "false").lower() == "true"


class ConsumerToolHandlersMixin:

    def submit_tool_output(
        self,
        *,
        thread_id: str,
        assistant_id: str,
        tool_call_id: Optional[str] = None,
        content: str,
        action: Any,
        is_error: bool = False,
    ) -> None:
        """Push tool output (or error) to the thread and update Action status."""
        if not content:
            content = ERROR_NO_CONTENT
        try:
            self.project_david_client.messages.submit_tool_output(
                thread_id=thread_id,
                content=content,
                role="tool",
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                tool_id=getattr(action, "id", "dummy"),
            )

            # Map bool to Enum
            final_status = StatusEnum.failed if is_error else StatusEnum.completed

            self.project_david_client.actions.update_action(
                action_id=action.id,
                status=final_status.value,
            )
        except Exception as exc:
            LOG.error("submit_tool_output failed: %s", exc, exc_info=True)
            self._submit_fallback_error(
                thread_id, assistant_id, f"ERROR: {exc}", action
            )

    def _submit_fallback_error(
        self,
        thread_id: str,
        assistant_id: str,
        *,
        tool_call_id: Optional[str] = None,
        error_msg: str,
        action: Any,
    ) -> None:
        """Fallback for critical submit_tool_output failures."""
        try:
            self.project_david_client.messages.submit_tool_output(
                thread_id=thread_id,
                content=error_msg,
                role="tool",
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                tool_id=getattr(action, "id", "dummy"),
            )
        finally:
            self.project_david_client.actions.update_action(
                action_id=action.id, status=StatusEnum.failed.value
            )

    def _format_error_payload(
        self, exc: Exception, include_traceback: bool = False
    ) -> str:
        """Structures errors for user-facing output."""
        error_data = {"error_type": exc.__class__.__name__, "message": str(exc)}
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
        tool_call_id: Optional[str] = None,
        action: Any,
    ) -> None:
        """Logs, surfaces, and propagates errors."""
        error_payload = self._format_error_payload(exc, SURFACE_TRACEBACK)
        LOG.error("Tool error [action=%s]: %s", action.id, error_payload, exc_info=True)
        self.submit_tool_output(
            thread_id=thread_id,
            assistant_id=assistant_id,
            tool_call_id=tool_call_id,
            content=error_payload,
            action=action,
            is_error=True,
        )
        raise exc

    def _process_tool_calls(
        self,
        thread_id: str,
        assistant_id: str,
        content: Dict[str, Any],
        run_id: str,
        *,
        tool_call_id: Optional[str] = None,
        api_key: Optional[str] = None,
        poll_interval: float = 1.0,
        max_wait: float = 60.0,
        # [NEW]
        decision: Optional[Dict] = None,
    ) -> Generator[str, None, None]:
        """
        Handles consumer-side tool calls.
        1. Creates Action in DB.
        2. Yields 'Manifest' (Action ID + Args) to client.
        3. Polls DB until client submits output (Blocking).
        """

        # 1. Create the Action Record with Decision Data
        action = self.project_david_client.actions.create_action(
            tool_name=content["name"],
            run_id=run_id,
            tool_call_id=tool_call_id,
            function_args=content["arguments"],
            # [NEW] Pass to API/Service
            decision=decision,
        )

        # 2. Construct & Yield the Manifest
        # This tells the client "Here is the ID you need to execute".

        if action.id:
            manifest_chunk = {
                "type": "tool_call_manifest",
                "run_id": run_id,
                "action_id": action.id,  # <--- Solves the race condition
                "tool": content["name"],
                "args": content["arguments"],
            }
            yield json.dumps(manifest_chunk)

        try:
            # 3. Signal that we are waiting
            self.project_david_client.runs.update_run_status(
                run_id, StatusEnum.pending_action.value
            )

            # 4. POLL (Blocking / Wait for Client)
            # The worker stays alive here while the client performs the execution
            # and POSTs the result back to the API.
            self._poll_for_completion(run_id, action.id, max_wait, poll_interval)

            LOG.debug("Tool %s completed/processed (run %s)", content["name"], run_id)

            # Optional: Yield a status update so client knows server saw the completion
            yield json.dumps(
                {"type": "status", "status": "tool_output_received", "run_id": run_id}
            )

        except Exception as exc:
            self._handle_tool_error(
                exc, thread_id=thread_id, assistant_id=assistant_id, action=action
            )
            # Ensure the client knows something went wrong during the wait
            yield json.dumps({"type": "error", "error": str(exc), "run_id": run_id})

    def _poll_for_completion(
        self, run_id: str, action_id: str, max_wait: float, poll_interval: float
    ) -> None:
        """
        Polls until the Action is completed OR the Run reaches a terminal state.
        """
        start = time.time()

        # Define terminal statuses that should break the polling loop
        terminal_run_statuses = {
            StatusEnum.completed.value,
            StatusEnum.failed.value,
            StatusEnum.cancelled.value,
            StatusEnum.expired.value,
            StatusEnum.deleted.value,
        }

        while True:
            # 1. Success condition: Are there no pending actions left?
            # (If empty, it means the consumer submitted and we marked it completed)
            pending = self.project_david_client.actions.get_pending_actions(
                run_id=run_id
            )
            if not pending:
                LOG.debug("Action %s resolved for run %s.", action_id, run_id)
                break

            # 2. Safety condition: Has the Run itself died/finished elsewhere?
            # (Prevents infinite loops if the user cancels the run while we wait)
            run = self.project_david_client.runs.retrieve_run(run_id)
            status_val = (
                run.status.value if hasattr(run.status, "value") else str(run.status)
            )

            if status_val in terminal_run_statuses:
                LOG.warning(
                    "Stopping tool poll. Run %s reached terminal state: %s",
                    run_id,
                    status_val,
                )
                break

            # 3. Timeout condition
            if time.time() - start > max_wait:
                raise TimeoutError(
                    f"Timeout waiting for action {action_id} (run {run_id})"
                )

            time.sleep(poll_interval)

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
        content: str = "",
        *,
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
            new_status=(
                StatusEnum.failed.value if is_error else StatusEnum.completed.value
            ),
        )
