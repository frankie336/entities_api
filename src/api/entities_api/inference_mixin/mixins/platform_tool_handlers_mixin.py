"""
Handlers for *platform-native* tools – i.e. the ones shipped with
Project David itself (web-search, code-interpreter, vector-store search,
remote shell, …).

A single public entry-point `_process_platform_tool_calls` decides which
private `_handle_*` branch to run and takes care of the Action / Run state
book-keeping.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
from typing import Any, Dict, List

from projectdavid_common import ValidationInterface

from entities_api.constants.assistant import \
    WEB_SEARCH_PRESENTATION_FOLLOW_UP_INSTRUCTIONS
from entities_api.constants.platform import ERROR_NO_CONTENT
from entities_api.services.logging_service import LoggingUtility

LOG = LoggingUtility()
logger = logging.getLogger(__name__)


class PlatformToolHandlersMixin:
    # ------------------------------------------------------------------ #
    # 🔑 Helpers reused by several handlers                               #
    # ------------------------------------------------------------------ #
    def _submit_platform_tool_output(
        self, *, thread_id: str, assistant_id: str, content: str, action
    ):
        """
        Thin wrapper around ConsumerToolHandlersMixin.submit_tool_output
        (kept separate to avoid circular import).
        """
        from .consumer_tool_handlers_mixin import ConsumerToolHandlersMixin

        if not isinstance(self, ConsumerToolHandlersMixin):  # type: ignore
            raise TypeError(
                "PlatformToolHandlersMixin must be combined with ConsumerToolHandlersMixin"
            )
        self.submit_tool_output(  # type: ignore[attr-defined]
            thread_id=thread_id,
            assistant_id=assistant_id,
            content=content,
            action=action,
        )

    # ------------------------------------------------------------------ #
    # 1️⃣  Individual handlers                                            #
    # ------------------------------------------------------------------ #
    def _handle_web_search(
        self, *, thread_id: str, assistant_id: str, output: List[Any], action
    ):
        """
        We expect the platform-side service to return a list of dicts.
        The *first* element already contains the “pretty” answer block.
        """
        try:
            rendered = f"{output[0]}{WEB_SEARCH_PRESENTATION_FOLLOW_UP_INSTRUCTIONS}"
            self._submit_platform_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                content=rendered,
                action=action,
            )
        except Exception as exc:  # ultra-defensive – a broken envelope must not crash
            LOG.error("web_search handler failed: %s", exc, exc_info=True)
            self._submit_platform_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                content=f"ERROR: {exc}",
                action=action,
            )

    def _handle_code_interpreter(
        self, *, thread_id: str, assistant_id: str, output: str, action
    ):
        """
        Upstream returns JSON with `"result": {"output": "…"}` – unwrap & post.
        """
        try:
            output_text = json.loads(output)["result"]["output"]
        except Exception as exc:
            LOG.error("code_interpreter output malformed: %s", exc, exc_info=True)
            output_text = f"ERROR: {exc}"

        self._submit_platform_tool_output(
            thread_id=thread_id,
            assistant_id=assistant_id,
            content=output_text,
            action=action,
        )

    def _handle_vector_search(
        self, *, thread_id: str, assistant_id: str, output: Any, action
    ):
        self._submit_platform_tool_output(
            thread_id=thread_id,
            assistant_id=assistant_id,
            content=str(output),
            action=action,
        )

    def _handle_computer(
        self, *, thread_id: str, assistant_id: str, output: str, action
    ):
        self._submit_platform_tool_output(
            thread_id=thread_id,
            assistant_id=assistant_id,
            content=output or ERROR_NO_CONTENT,
            action=action,
        )

    # ------------------------------------------------------------------ #
    # 2️⃣  Main dispatcher (called by ToolRoutingMixin)                   #
    # ------------------------------------------------------------------ #
    def _process_platform_tool_calls(
        self,
        thread_id: str,
        assistant_id: str,
        content: Dict[str, Any],
        run_id: str,
    ):
        """
        • creates an *Action* row
        • flips the Run → `pending_action`
        • calls the real platform service via `PlatformToolService`
        • routes the result to one of _handle_* helpers above
        """
        # Lazily import to avoid hard coupling
        from entities_api.ptool_handlers.platform_tool_service import \
            PlatformToolService

        # --- 0. derive helpers & ids -------------------------------------
        self.set_assistant_id(assistant_id)  # type: ignore[attr-defined]
        self.set_thread_id(thread_id)  # type: ignore[attr-defined]
        tool_name = content["name"]
        arguments = content["arguments"]

        # --- 1. create Action -------------------------------------------
        action = self.project_david_client.actions.create_action(
            tool_name="code_interpreter", run_id=run_id, function_args=arguments
        )

        LOG.debug("Action %s created for %s", action.id, tool_name)

        # --- 2. mark run → pending_action -------------------------------
        self.run_service.update_run_status(  # type: ignore
            run_id, ValidationInterface.StatusEnum.pending_action
        )

        # --- 3. call platform service -----------------------------------
        platform = self.platform_tool_service  # type: ignore[attr-defined]
        result = platform.call_function(tool_name, arguments)

        # --- 4. fan-out to handler --------------------------------------
        handlers = {
            "web_search": self._handle_web_search,
            "code_interpreter": self._handle_code_interpreter,
            "vector_store_search": self._handle_vector_search,
            "computer": self._handle_computer,
        }

        handler = handlers.get(tool_name)
        if handler:
            handler(
                thread_id=thread_id,
                assistant_id=assistant_id,
                output=result,
                action=action,
            )
        else:
            # fallback – treat as plain text
            self._submit_platform_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                content=str(result),
                action=action,
            )

        LOG.debug("Platform-tool %s finished for run %s", tool_name, run_id)
