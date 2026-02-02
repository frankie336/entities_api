# src/api/entities_api/orchestration/mixins/consumer_tool_handlers_mixin.py
from __future__ import annotations

import asyncio
import json
import logging
import os
import traceback
from typing import Any, AsyncGenerator, Dict, Optional

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

    async def submit_tool_output(
        self,
        *,
        thread_id: str,
        assistant_id: str,
        tool_call_id: Optional[str] = None,
        content: str,
        action: Any,
        is_error: bool = False,
    ) -> None:
        """Push tool output to thread and update Action status (Async)."""
        if not content:
            content = ERROR_NO_CONTENT

        final_status = StatusEnum.failed if is_error else StatusEnum.completed

        try:
            # Offload sync client calls to threads
            await asyncio.to_thread(
                self.project_david_client.messages.submit_tool_output,
                thread_id=thread_id,
                content=content,
                role="tool",
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                tool_id=getattr(action, "id", "dummy"),
            )

            await asyncio.to_thread(
                self.project_david_client.actions.update_action,
                action_id=action.id,
                status=final_status.value,
            )
        except Exception as exc:
            LOG.error("submit_tool_output failed: %s", exc, exc_info=True)
            await self._submit_fallback_error(
                thread_id, assistant_id, error_msg=f"ERROR: {exc}", action=action
            )

    async def _submit_fallback_error(
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
            await asyncio.to_thread(
                self.project_david_client.messages.submit_tool_output,
                thread_id=thread_id,
                content=error_msg,
                role="tool",
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                tool_id=getattr(action, "id", "dummy"),
            )
        finally:
            await asyncio.to_thread(
                self.project_david_client.actions.update_action,
                action_id=action.id,
                status=StatusEnum.failed.value,
            )

    def _format_error_payload(self, exc: Exception, include_traceback: bool = False) -> str:
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

    async def _handle_tool_error(
        self,
        exc: Exception,
        *,
        thread_id: str,
        assistant_id: str,
        tool_call_id: Optional[str] = None,
        action: Any,
    ) -> None:
        """Logs and surfaces errors asynchronously."""
        error_payload = self._format_error_payload(exc, SURFACE_TRACEBACK)
        LOG.error(
            "Tool error [action=%s]: %s",
            getattr(action, "id", "unknown"),
            error_payload,
            exc_info=True,
        )
        await self.submit_tool_output(
            thread_id=thread_id,
            assistant_id=assistant_id,
            tool_call_id=tool_call_id,
            content=error_payload,
            action=action,
            is_error=True,
        )

    # ------------------------------------------------------------------
    # ASYNC TOOL CALL PROCESSOR (Reactive Mode - No Polling)
    # ------------------------------------------------------------------
    async def _process_tool_calls(
        self,
        thread_id: str,
        assistant_id: str,
        content: Dict[str, Any],
        run_id: str,
        *,
        tool_call_id: Optional[str] = None,
        decision: Optional[Dict] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """
        Reactive Mode: Yield manifest and RETURN.
        Client will execute and initiate Turn 2 in a NEW request.
        """
        tool_name = content.get("name") or content.get("tool_name")
        tool_args = content.get("arguments") or content.get("args") or {}

        # 1. Create Action
        action = await asyncio.to_thread(
            self.project_david_client.actions.create_action,
            tool_name=tool_name,
            run_id=run_id,
            tool_call_id=tool_call_id,
            function_args=tool_args,
            decision=decision,
        )

        # 2. Yield manifest
        if action and action.id:
            yield json.dumps(
                {
                    "type": "tool_call_manifest",
                    "run_id": run_id,
                    "action_id": action.id,
                    "tool": tool_name,
                    "args": tool_args,
                }
            )

        # 3. Set status to pending
        await asyncio.to_thread(
            self.project_david_client.runs.update_run_status,
            run_id,
            StatusEnum.pending_action.value,
        )
        return  # Terminate stream

    async def finalize_conversation(
        self,
        assistant_reply: str,
        thread_id: str,
        assistant_id: str,
        run_id: str,
        final_status: Optional[str] = None,  # NEW: Allow overriding the auto-complete
    ) -> None:
        if not assistant_reply:
            return

        await asyncio.to_thread(
            self._save_assistant_message,
            thread_id,
            assistant_id,
            run_id,
            assistant_reply,
            is_error=False,
            forced_status=final_status,  # Pass the status through
        )

    async def finalize_conversation(
        self, assistant_reply: str, thread_id: str, assistant_id: str, run_id: str
    ) -> None:
        """Saves final output and marks run completed (Async)."""
        if not assistant_reply:
            return
        LOG.info(f"TOOL-ROUTER ▸ Finalizing run {run_id}")
        await asyncio.to_thread(
            self._save_assistant_message,
            thread_id,
            assistant_id,
            run_id,
            assistant_reply,
            is_error=False,
        )

    async def handle_error(
        self, assistant_reply: str, thread_id: str, assistant_id: str, run_id: str
    ) -> None:
        """Saves partial output and marks run failed (Async)."""
        await asyncio.to_thread(
            self._save_assistant_message,
            thread_id,
            assistant_id,
            run_id,
            assistant_reply or "An error occurred.",
            is_error=True,
        )

    def _save_assistant_message(
        self,
        thread_id: str,
        assistant_id: str,
        run_id: str,
        content: str = "",
        *,
        is_error: bool,
        forced_status: Optional[str] = None # NEW parameter
    ) -> None:
        self.project_david_client.messages.save_assistant_message_chunk(
            thread_id=thread_id,
            content=content,
            role="assistant",
            assistant_id=assistant_id,
            sender_id=assistant_id,
            is_last_chunk=True,
        )

        # FIX: Only update status if not explicitly overridden
        status = forced_status or (StatusEnum.failed.value if is_error else StatusEnum.completed.value)
        self.project_david_client.runs.update_run_status(run_id=run_id, new_status=status)
