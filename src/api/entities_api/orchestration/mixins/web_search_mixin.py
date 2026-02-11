# src/api/entities_api/orchestration/mixins/web_search_mixin.py
from __future__ import annotations

import asyncio
import re
from typing import Any, AsyncGenerator, Dict, Optional

from projectdavid.events import StatusEvent
from projectdavid_common import ToolValidator
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from src.api.entities_api.utils.level3_utils import create_status_payload

LOG = LoggingUtility()


class WebSearchMixin:
    """
    Drive the **Level 3 Agentic Web Tools** (read, scroll, search, discovery).
    """

    @staticmethod
    def _format_web_tool_error(tool_name: str, error_content: str, inputs: Dict) -> str:
        """
        Translates web/validation failures into actionable Level 2 instructions.
        """
        if not error_content:
            error_content = "Unknown Error (Empty Response)"

        error_lower = error_content.lower()

        # --- 1. SCHEMA/VALIDATION RECOVERY (The Fix for your issue) ---
        if "validation error" in error_lower or "missing arguments" in error_lower:
            # Specific handling for the search_web_page 'query' issue
            if tool_name == "search_web_page" and "query" in error_lower:
                return (
                    f"❌ CRITICAL SCHEMA ERROR: The tool '{tool_name}' failed.\n"
                    f"REASON: You forgot the required 'query' argument.\n"
                    f"YOU SENT: {inputs}\n"
                    f"REQUIRED FORMAT: search_web_page(url='...', query='TARGET_KEYWORD')\n"
                    "SYSTEM INSTRUCTION: Immediate Correction Required. Call the tool again with the 'query' parameter included."
                )

            # Generic Schema Fix
            return (
                f"❌ SCHEMA ERROR: Invalid arguments for '{tool_name}'.\n"
                f"ERROR DETAILS: {error_content}\n"
                "SYSTEM INSTRUCTION: Check the tool definition and retry with valid arguments."
            )

        # --- 2. ACCESS DENIED ---
        if "403" in error_content or "access denied" in error_lower:
            return (
                f"❌ Web Tool '{tool_name}' Failed: Access Denied (Bot Protection).\n"
                "SYSTEM INSTRUCTION: This URL is blocking bots. STOP trying this specific URL. "
                "Pick a different URL from your search results."
            )

        # --- 3. PAGINATION LIMITS ---
        if "out of bounds" in error_lower or "invalid page" in error_lower:
            return (
                f"⚠️ Web Tool '{tool_name}' Note: End of Document Reached.\n"
                "SYSTEM INSTRUCTION: No more pages. Synthesize collected info."
            )

        # --- 4. EMPTY SEARCH RESULTS ---
        if "not found" in error_lower and tool_name == "search_web_page":
            query = inputs.get("query", "unknown")
            return (
                f"⚠️ Web Search Result for '{query}': 0 matches found.\n"
                "SYSTEM INSTRUCTION: Keyword not found.\n"
                "1. Try a broader keyword (e.g., 'Revenue' instead of 'Q3 2024 Revenue').\n"
                "2. Or call `read_web_page` to check metadata."
            )

        return (
            f"❌ Web Tool '{tool_name}' Error: {error_content}\n"
            "SYSTEM INSTRUCTION: Review arguments. If error persists, stop using this tool."
        )

    # ... (_inject_navigation_guidance and _parse_serp_results remain the same) ...
    def _inject_navigation_guidance(self, content: str, url: str) -> str:
        if not content:
            return ""
        page_match = re.search(
            r"Page\s+(\d+)\s*(?:of|/)\s*(\d+)", content, re.IGNORECASE
        )
        if not page_match:
            return content

        curr, total = int(page_match.group(1)), int(page_match.group(2))
        next_p = curr + 1

        if curr >= total - 1:
            return content + "\n\n--- ✅ END OF DOCUMENT ---"

        return (
            content + f"\n\n--- 🧭 NAVIGATION (Page {curr}/{total}) ---\n"
            f"1. [STOP] if you have the answer.\n"
            f"2. [SEARCH] 'search_web_page' for keywords.\n"
            f"3. [SCROLL] 'scroll_web_page' to page {next_p}."
        )

    def _parse_serp_results(self, raw_markdown: str, query: str) -> str:
        if not raw_markdown:
            return f"Error: No data for '{query}'."
        lines = raw_markdown.split("\n")
        results = []
        count = 0
        for line in lines:
            if count >= 5:
                break
            if "](" in line and "duckduckgo" not in line:
                match = re.search(r"\((https?://[^)]+)\)", line)
                if match:
                    title = line.split("](")[0].strip("[")
                    results.append(f"{count+1}. **{title}** -> {match.group(1)}")
                    count += 1
        return (
            f"SEARCH RESULTS for '{query}':\n" + "\n".join(results)
            if results
            else "No results."
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
    ) -> AsyncGenerator[StatusEvent, None]:
        """
        Shared core logic for Read, Scroll, Search, and SERP.
        """
        ts_start = asyncio.get_event_loop().time()

        # --- [1] STATUS: VALIDATING ---
        yield create_status_payload(run_id, tool_name, "Validating parameters...")

        # --- VALIDATION ---
        validator = ToolValidator()
        validator.schema_registry = {tool_name: required_keys}
        validation_error = validator.validate_args(tool_name, arguments_dict)

        # --- [CRITICAL FIX] HANDLE VALIDATION FAILURE BY SUBMITTING OUTPUT ---
        if validation_error:
            LOG.warning(f"{tool_name} ▸ Validation Failed: {validation_error}")

            # 1. Notify Frontend
            yield create_status_payload(
                run_id, tool_name, "Validation failed. Retrying...", state="error"
            )

            # 2. Construct the Pedagogical Error Message
            error_feedback = self._format_web_tool_error(
                tool_name, f"Validation Error: {validation_error}", arguments_dict
            )

            # 3. Create Action (So we have something to attach the failure to)
            # We create a failed action record for telemetry
            try:
                action = await asyncio.to_thread(
                    self.project_david_client.actions.create_action,
                    tool_name=tool_name,
                    run_id=run_id,
                    tool_call_id=tool_call_id,
                    function_args=arguments_dict,
                    decision=decision,
                )

                # 4. Submit the Failure to the LLM
                await self.submit_tool_output(
                    thread_id=thread_id,
                    assistant_id=assistant_id,
                    tool_call_id=tool_call_id,
                    content=error_feedback,
                    action=action,
                    is_error=True,
                )

                # 5. Mark Action Failed
                await asyncio.to_thread(
                    self.project_david_client.actions.update_action,
                    action_id=action.id,
                    status=StatusEnum.failed.value,
                )
            except Exception as e:
                LOG.error(f"Failed to submit validation error: {e}")

            return  # Stop execution here, LLM will see error and retry next turn

        # --- [2] STATUS: CREATING ACTION (Success Path) ---
        yield create_status_payload(run_id, tool_name, "Initializing tool action...")

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
            LOG.error(f"{tool_name} ▸ Action creation failed: {e}")
            yield create_status_payload(
                run_id, tool_name, "Internal system error.", state="error"
            )
            return

        # --- [3] EXECUTION (Threaded I/O) ---
        try:
            final_content = ""

            # ... (Tool Execution Logic A/B/C/D remains exactly as you had it) ...
            if tool_name == "read_web_page":
                target_url = arguments_dict["url"]
                yield create_status_payload(
                    run_id, tool_name, f"Reading: {target_url}..."
                )
                raw_content = await asyncio.to_thread(
                    self.project_david_client.tools.web_read,
                    url=target_url,
                    force_refresh=arguments_dict.get("force_refresh", False),
                )
                final_content = self._inject_navigation_guidance(
                    raw_content, target_url
                )

            elif tool_name == "scroll_web_page":
                target_url = arguments_dict["url"]
                page_num = arguments_dict["page"]
                yield create_status_payload(
                    run_id, tool_name, f"Scrolling to page {page_num}..."
                )
                raw_content = await asyncio.to_thread(
                    self.project_david_client.tools.web_scroll,
                    url=target_url,
                    page=page_num,
                )
                final_content = self._inject_navigation_guidance(
                    raw_content, target_url
                )

            elif tool_name == "search_web_page":
                target_url = arguments_dict["url"]
                query_val = arguments_dict["query"]
                yield create_status_payload(
                    run_id, tool_name, f"Searching page for '{query_val}'..."
                )
                final_content = await asyncio.to_thread(
                    self.project_david_client.tools.web_search,
                    url=target_url,
                    query=query_val,
                )

            elif tool_name == "perform_web_search":
                query_val = arguments_dict["query"]
                yield create_status_payload(
                    run_id, tool_name, f"Querying search engine: '{query_val}'..."
                )
                query_str = query_val.replace(" ", "+")
                raw_serp = await asyncio.to_thread(
                    self.project_david_client.tools.web_read,
                    url=f"https://html.duckduckgo.com/html/?q={query_str}",
                    force_refresh=True,
                )
                yield create_status_payload(
                    run_id, tool_name, "Parsing search results..."
                )
                final_content = self._parse_serp_results(raw_serp, query_val)

            else:
                raise ValueError(f"Unknown web tool: {tool_name}")

            # --- [4] RESULT ANALYSIS ---
            if final_content is None:
                final_content = "❌ Error: Tool execution returned no data."

            is_soft_failure = (
                "❌ Error" in final_content or "Error:" in str(final_content)[0:50]
            )

            if is_soft_failure:
                yield create_status_payload(
                    run_id, tool_name, "Encountered external error...", state="warning"
                )
                final_content = self._format_web_tool_error(
                    tool_name, final_content, arguments_dict
                )
            else:
                yield create_status_payload(
                    run_id,
                    tool_name,
                    "Content retrieved successfully.",
                    state="success",
                )

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
                "[%s] %s completed in %.2fs",
                run_id,
                tool_name,
                asyncio.get_event_loop().time() - ts_start,
            )

        except Exception as exc:
            # --- [7] HARD FAILURE HANDLING ---
            LOG.error(f"[%s] %s HARD FAILURE: {exc}", run_id, tool_name)
            yield create_status_payload(
                run_id, tool_name, f"Critical failure: {str(exc)}", state="error"
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
            except Exception:
                pass

    # ------------------------------------------------------------------
    # PUBLIC HANDLERS
    # ------------------------------------------------------------------
    async def handle_perform_web_search(
        self,
        thread_id: str,
        run_id: str,
        assistant_id: str,
        arguments_dict: Dict[str, Any],
        tool_call_id: Optional[str] = None,
        decision: Optional[Dict] = None,
    ) -> AsyncGenerator[StatusEvent, None]:
        """Handler for 'perform_web_search' (Google/DDG Discovery)."""
        async for status in self._execute_web_tool_logic(
            tool_name="perform_web_search",
            required_keys=["query"],
            thread_id=thread_id,
            run_id=run_id,
            assistant_id=assistant_id,
            arguments_dict=arguments_dict,
            tool_call_id=tool_call_id,
            decision=decision,
        ):
            yield status

    async def handle_read_web_page(
        self,
        thread_id: str,
        run_id: str,
        assistant_id: str,
        arguments_dict: Dict[str, Any],
        tool_call_id: Optional[str] = None,
        decision: Optional[Dict] = None,
    ) -> AsyncGenerator[StatusEvent, None]:
        async for status in self._execute_web_tool_logic(
            tool_name="read_web_page",
            required_keys=["url"],
            thread_id=thread_id,
            run_id=run_id,
            assistant_id=assistant_id,
            arguments_dict=arguments_dict,
            tool_call_id=tool_call_id,
            decision=decision,
        ):
            yield status

    async def handle_scroll_web_page(
        self,
        thread_id: str,
        run_id: str,
        assistant_id: str,
        arguments_dict: Dict[str, Any],
        tool_call_id: Optional[str] = None,
        decision: Optional[Dict] = None,
    ) -> AsyncGenerator[StatusEvent, None]:
        async for status in self._execute_web_tool_logic(
            tool_name="scroll_web_page",
            required_keys=["url", "page"],
            thread_id=thread_id,
            run_id=run_id,
            assistant_id=assistant_id,
            arguments_dict=arguments_dict,
            tool_call_id=tool_call_id,
            decision=decision,
        ):
            yield status

    async def handle_search_web_page(
        self,
        thread_id: str,
        run_id: str,
        assistant_id: str,
        arguments_dict: Dict[str, Any],
        tool_call_id: Optional[str] = None,
        decision: Optional[Dict] = None,
    ) -> AsyncGenerator[StatusEvent, None]:
        async for status in self._execute_web_tool_logic(
            tool_name="search_web_page",
            required_keys=["url", "query"],
            thread_id=thread_id,
            run_id=run_id,
            assistant_id=assistant_id,
            arguments_dict=arguments_dict,
            tool_call_id=tool_call_id,
            decision=decision,
        ):
            yield status
