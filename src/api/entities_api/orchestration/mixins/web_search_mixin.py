# src/api/entities_api/orchestration/mixins/web_search_mixin.py
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional

from projectdavid_common import ToolValidator
from projectdavid_common.validation import StatusEnum


from projectdavid_common.utilities.logging_service import LoggingUtility

LOG = LoggingUtility()


class WebSearchMixin:
    """
    Drive the **Level 3 Agentic Web Tools** (read, scroll, search).

    Implementation includes:
    1. Schema validation per tool.
    2. Automated self-correction hints for 403s, 404s, or empty search results.
    3. Action lifecycle tracking (pending -> completed/failed).
    """

    @staticmethod
    def _format_web_tool_error(tool_name: str, error_content: str, inputs: Dict) -> str:
        """
        Translates web failures into actionable Level 2 instructions for the LLM.
        """
        if "403" in error_content or "Access Denied" in error_content:
            return (
                f"Web Tool '{tool_name}' Failed: Access Denied (Bot Protection).\n"
                "INSTRUCTION: This specific URL is blocking automated access. "
                "Do NOT retry this URL. Please search for a different source/URL for this information."
            )

        if "out of bounds" in error_content.lower():
            return (
                f"Web Tool '{tool_name}' Failed: {error_content}\n"
                "INSTRUCTION: You have reached the end of the document. "
                "Do not attempt to scroll further. Synthesize what you have read so far."
            )

        if "not found" in error_content.lower() and tool_name == "search_web_page":
            query = inputs.get("query", "unknown")
            return (
                f"Web Search Result for '{query}': No matches found.\n"
                "INSTRUCTION: The specific keyword was not found. Try again with a "
                "shorter, broader keyword (e.g., instead of 'Q3 2024 Revenue', try 'Revenue')."
            )

        # Generic Fallback
        return (
            f"Web Tool '{tool_name}' Error: {error_content}\n"
            "INSTRUCTION: Review the arguments. If the URL is invalid, correct it. "
            "If the error persists, stop using this tool for this request."
        )

    async def _execute_web_tool_logic(
        self,
        tool_name: str,
        required_keys: list[str],
        thread_id: str,
        run_id: str,
        assistant_id: str,
        arguments_dict: Dict[str, Any],
        tool_call_id: Optional[str],
        decision: Optional[Dict],
    ) -> None:
        """
        Shared core logic for Read, Scroll, and Search.
        Reduces code duplication while maintaining strict logging and state management.
        """
        ts_start = asyncio.get_event_loop().time()

        # --- [1] VALIDATION ---
        validator = ToolValidator()
        validator.schema_registry = {tool_name: required_keys}

        validation_error = validator.validate_args(tool_name, arguments_dict)

        if validation_error:
            LOG.warning(f"{tool_name} ▸ Validation Failed: {validation_error}")

            # Create failed action record
            try:
                action = await asyncio.to_thread(
                    self.project_david_client.actions.create_action,
                    tool_name=tool_name,
                    run_id=run_id,
                    tool_call_id=tool_call_id,
                    function_args=arguments_dict,
                    decision=decision,
                )
                await asyncio.to_thread(
                    self.project_david_client.actions.update_action,
                    action_id=action.id,
                    status=StatusEnum.failed.value,
                )
            except Exception:
                pass

            # Submit error to orchestrator to force retry/correction
            await self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                content=f"Schema Validation Error: {validation_error}",
                action=action if "action" in locals() else None,
                is_error=True,
            )
            return

        # --- [2] ACTION CREATION (Pending) ---
        try:
            action = await asyncio.to_thread(
                self.project_david_client.actions.create_action,
                tool_name=tool_name,
                run_id=run_id,
                tool_call_id=tool_call_id,
                function_args=arguments_dict,
                decision=decision,
            )
        except Exception as e:
            LOG.error(f"{tool_name} ▸ Action creation failed for run {run_id}: {e}")
            return

        # --- [3] EXECUTION (Threaded I/O) ---
        try:
            # Dispatch to specific client method based on tool_name
            if tool_name == "read_web_page":
                result_content = await asyncio.to_thread(
                    self.project_david_client.tools.web_read,
                    url=arguments_dict["url"],
                    force_refresh=arguments_dict.get("force_refresh", False),
                )
            elif tool_name == "scroll_web_page":
                result_content = await asyncio.to_thread(
                    self.project_david_client.tools.web_scroll,
                    url=arguments_dict["url"],
                    page=arguments_dict["page"],
                )
            elif tool_name == "search_web_page":
                result_content = await asyncio.to_thread(
                    self.project_david_client.tools.web_search,
                    url=arguments_dict["url"],
                    query=arguments_dict["query"],
                )
            else:
                raise ValueError(f"Unknown web tool: {tool_name}")

            # --- [4] RESULT ANALYSIS (Soft Failure Detection) ---
            # Check if the tool returned an internal error string (e.g., "❌ Error: ...")
            is_soft_failure = (
                "❌ Error" in result_content or "Error:" in result_content[0:50]
            )

            if is_soft_failure:
                # Format it as an instruction
                final_content = self._format_web_tool_error(
                    tool_name, result_content, arguments_dict
                )
                LOG.warning(f"{tool_name} ▸ Soft Failure: {result_content[:100]}...")
            else:
                final_content = result_content

            # --- [5] SUBMIT OUTPUT ---
            await self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                content=final_content,
                action=action,
                is_error=is_soft_failure,
            )

            # --- [6] UPDATE STATUS ---
            await asyncio.to_thread(
                self.project_david_client.actions.update_action,
                action_id=action.id,
                status=(
                    StatusEnum.completed.value
                    if not is_soft_failure
                    else StatusEnum.failed.value
                ),
            )

            LOG.info(
                "[%s] %s completed in %.2fs (action=%s)",
                run_id,
                tool_name,
                asyncio.get_event_loop().time() - ts_start,
                action.id,
            )

        except Exception as exc:
            # --- [7] HARD FAILURE HANDLING ---
            LOG.error(
                f"[%s] %s HARD FAILURE action=%s exc=%s",
                run_id,
                tool_name,
                action.id,
                exc,
            )

            error_hint = self._format_web_tool_error(
                tool_name, str(exc), arguments_dict
            )

            try:
                await asyncio.to_thread(
                    self.project_david_client.actions.update_action,
                    action_id=action.id,
                    status=StatusEnum.failed.value,
                )

                await self.submit_tool_output(
                    thread_id=thread_id,
                    assistant_id=assistant_id,
                    tool_call_id=tool_call_id,
                    content=error_hint,
                    action=action,
                    is_error=True,
                )
            except Exception as inner:
                LOG.exception(
                    "[%s] Critical failure during error surfacing: %s", run_id, inner
                )

    # ------------------------------------------------------------------
    # PUBLIC HANDLERS (Entry Points)
    # ------------------------------------------------------------------

    async def handle_read_web_page(
        self,
        thread_id: str,
        run_id: str,
        assistant_id: str,
        arguments_dict: Dict[str, Any],
        tool_call_id: Optional[str] = None,
        decision: Optional[Dict] = None,
    ) -> None:
        """Handler for 'read_web_page'."""
        await self._execute_web_tool_logic(
            tool_name="read_web_page",
            required_keys=["url"],
            thread_id=thread_id,
            run_id=run_id,
            assistant_id=assistant_id,
            arguments_dict=arguments_dict,
            tool_call_id=tool_call_id,
            decision=decision,
        )

    async def handle_scroll_web_page(
        self,
        thread_id: str,
        run_id: str,
        assistant_id: str,
        arguments_dict: Dict[str, Any],
        tool_call_id: Optional[str] = None,
        decision: Optional[Dict] = None,
    ) -> None:
        """Handler for 'scroll_web_page'."""
        await self._execute_web_tool_logic(
            tool_name="scroll_web_page",
            required_keys=["url", "page"],
            thread_id=thread_id,
            run_id=run_id,
            assistant_id=assistant_id,
            arguments_dict=arguments_dict,
            tool_call_id=tool_call_id,
            decision=decision,
        )

    async def handle_search_web_page(
        self,
        thread_id: str,
        run_id: str,
        assistant_id: str,
        arguments_dict: Dict[str, Any],
        tool_call_id: Optional[str] = None,
        decision: Optional[Dict] = None,
    ) -> None:
        """Handler for 'search_web_page'."""
        await self._execute_web_tool_logic(
            tool_name="search_web_page",
            required_keys=["url", "query"],
            thread_id=thread_id,
            run_id=run_id,
            assistant_id=assistant_id,
            arguments_dict=arguments_dict,
            tool_call_id=tool_call_id,
            decision=decision,
        )
