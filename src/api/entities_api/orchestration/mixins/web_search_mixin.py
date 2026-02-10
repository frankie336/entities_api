# src/api/entities_api/orchestration/mixins/web_search_mixin.py
# src/api/entities_api/orchestration/mixins/web_search_mixin.py
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, AsyncGenerator, Dict, Optional

from projectdavid.events import StatusEvent
from projectdavid_common import ToolValidator
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

LOG = LoggingUtility()


class WebSearchMixin:
    """
    Drive the **Level 3 Agentic Web Tools** (read, scroll, search, discovery).
    """

    def _create_status_payload(
        self, run_id: str, tool_name: str, message: str, state: str = "running"
    ) -> StatusEvent:
        return StatusEvent(
            run_id=run_id,
            status=state,
            tool=tool_name,
            message=message,
        )

    @staticmethod
    def _format_web_tool_error(tool_name: str, error_content: str, inputs: Dict) -> str:
        """
        Translates web failures into actionable Level 2 instructions for the LLM.
        """
        # Safety check: ensure error_content is a string
        if not error_content:
            error_content = "Unknown Error (Empty Response)"

        error_lower = error_content.lower()

        if "403" in error_content or "access denied" in error_lower:
            return (
                f"❌ Web Tool '{tool_name}' Failed: Access Denied (Bot Protection).\n"
                "SYSTEM INSTRUCTION: This specific URL is blocking automated access. "
                "STOP trying this URL. Pick a different URL from your search results."
            )

        if "out of bounds" in error_lower or "invalid page" in error_lower:
            return (
                f"⚠️ Web Tool '{tool_name}' Note: End of Document Reached.\n"
                "SYSTEM INSTRUCTION: There are no more pages to scroll. "
                "Synthesize the information you have collected so far."
            )

        if "not found" in error_lower and tool_name == "search_web_page":
            query = inputs.get("query", "unknown")
            return (
                f"⚠️ Web Search Result for '{query}': 0 matches found.\n"
                "SYSTEM INSTRUCTION: The specific keyword was not found on this page.\n"
                "1. Try a broader keyword (e.g., instead of 'Q3 2024 Revenue', try 'Revenue').\n"
                "2. Or call `read_web_page` to check metadata/summaries."
            )

        return (
            f"❌ Web Tool '{tool_name}' Error: {error_content}\n"
            "SYSTEM INSTRUCTION: Review the arguments. If the error persists, stop using this tool."
        )

    def _inject_navigation_guidance(self, content: str, url: str) -> str:
        """
        Parses the content for pagination info and appends specific Level 3 instructions.
        """
        # CRASH FIX: Handle cases where content is None or empty
        if not content:
            return ""

        # Regex to find "Page X of Y" (Matches: "Page 0 of 5", "Page 1 / 10")
        page_match = re.search(
            r"Page\s+(\d+)\s*(?:of|/)\s*(\d+)", content, re.IGNORECASE
        )

        # HALLUCINATION FIX:
        # If no pagination is detected, DO NOT INJECT ANYTHING.
        # Injecting "hints" here causes the model to fake-type tool calls.
        if not page_match:
            return content

        current_page = int(page_match.group(1))
        total_pages = int(page_match.group(2))
        next_page = current_page + 1

        # OPTION B: Last page reached
        if current_page >= total_pages - 1:
            return (
                content
                + "\n\n--- ✅ END OF DOCUMENT ---\n(No further scrolling possible. Synthesize your findings now.)"
            )

        # OPTION C: Pagination exists - USE NATURAL LANGUAGE ONLY
        # We removed the `search_web_page(...)` syntax to prevent token leakage.
        footer = (
            f"\n\n--- 🧭 LEVEL 3 NAVIGATION PANEL (Current: Page {current_page} of {total_pages}) ---\n"
            f"The document continues. Status check:\n\n"
            f"1. [STOP]: If you have the answer, stop and synthesize immediately.\n"
            f"2. [SEARCH]: If facts are missing, perform a 'search_web_page' action for specific keywords.\n"
            f"3. [SCROLL]: If reading a narrative, perform a 'scroll_web_page' action to read page {next_page}."
        )
        return content + footer

    def _parse_serp_results(self, raw_markdown: str, query: str) -> str:
        """
        Parses raw markdown from a SERP (DuckDuckGo HTML) into a clean list of URLs.
        """
        # CRASH FIX: Handle None input
        if not raw_markdown:
            return f"❌ Error: Search Engine returned no data for '{query}'."

        lines = raw_markdown.split("\n")
        results = []
        count = 0

        for line in lines:
            if count >= 5:
                break
            if "](" in line and "duckduckgo.com" not in line:
                match = re.search(r"\((https?://[^)]+)\)", line)
                if match:
                    url = match.group(1)
                    title = line.split("](")[0].strip("[")
                    results.append(f"{count+1}. **{title}**\n   LINK: {url}")
                    count += 1

        if not results:
            return (
                f"❌ No clear search results found for '{query}'.\n"
                "SYSTEM DIAGNOSTIC: The search engine returned content that could not be parsed (possibly a CAPTCHA).\n"
                "INSTRUCTION: \n"
                "1. Try a slightly different query (simpler terms).\n"
                "2. Or if you have a specific URL in mind, use `read_web_page` directly."
            )

        header = f"--- 🔎 SEARCH RESULTS FOR: '{query}' ---\n"
        instructions = "\n\n👉 SYSTEM INSTRUCTION: To read a result, use `read_web_page(url='...')` on one of the links above."
        return header + "\n".join(results) + instructions

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
        Shared core logic for Read, Scroll, Search, and SERP (Global Search).
        Yields status messages to the Orchestrator for frontend rendering.
        """
        ts_start = asyncio.get_event_loop().time()

        # --- [1] STATUS: VALIDATING ---
        yield self._create_status_payload(run_id, tool_name, "Validating parameters...")

        # --- VALIDATION ---
        validator = ToolValidator()
        validator.schema_registry = {tool_name: required_keys}
        validation_error = validator.validate_args(tool_name, arguments_dict)

        if validation_error:
            LOG.warning(f"{tool_name} ▸ Validation Failed: {validation_error}")
            yield self._create_status_payload(
                run_id, tool_name, "Validation failed.", state="error"
            )
            # ... (Error handling logic unchanged) ...
            return

        # --- [2] STATUS: CREATING ACTION ---
        yield self._create_status_payload(
            run_id, tool_name, "Initializing tool action..."
        )

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
            yield self._create_status_payload(
                run_id, tool_name, "Internal system error.", state="error"
            )
            return

        # --- [3] EXECUTION (Threaded I/O) ---
        try:
            final_content = ""

            # --- A. READ PAGE ---
            if tool_name == "read_web_page":
                target_url = arguments_dict["url"]
                yield self._create_status_payload(
                    run_id, tool_name, f"Reading: {target_url}..."
                )

                raw_content = await asyncio.to_thread(
                    self.project_david_client.tools.web_read,
                    url=target_url,
                    force_refresh=arguments_dict.get("force_refresh", False),
                )

                # CRASH FIX: Catch None return
                if raw_content is None:
                    raw_content = "❌ Error: Failed to retrieve page content (Connection Failed or Empty)."

                yield self._create_status_payload(
                    run_id, tool_name, "Analyzing page content..."
                )
                final_content = self._inject_navigation_guidance(
                    raw_content, target_url
                )

            # --- B. SCROLL PAGE ---
            elif tool_name == "scroll_web_page":
                target_url = arguments_dict["url"]
                page_num = arguments_dict["page"]
                yield self._create_status_payload(
                    run_id, tool_name, f"Scrolling to page {page_num}..."
                )

                raw_content = await asyncio.to_thread(
                    self.project_david_client.tools.web_scroll,
                    url=target_url,
                    page=page_num,
                )

                # CRASH FIX: Catch None return
                if raw_content is None:
                    raw_content = f"❌ Error: Failed to scroll to page {page_num}."

                final_content = self._inject_navigation_guidance(
                    raw_content, target_url
                )

            # --- C. INTERNAL SEARCH (Ctrl+F) ---
            elif tool_name == "search_web_page":
                target_url = arguments_dict["url"]
                query_val = arguments_dict["query"]
                yield self._create_status_payload(
                    run_id, tool_name, f"Searching page for '{query_val}'..."
                )

                final_content = await asyncio.to_thread(
                    self.project_david_client.tools.web_search,
                    url=target_url,
                    query=query_val,
                )

                # CRASH FIX: Catch None return
                if final_content is None:
                    final_content = f"❌ Error: Search failed for '{query_val}'."

            # --- D. GLOBAL SEARCH (SERP) ---
            elif tool_name == "perform_web_search":
                query_val = arguments_dict["query"]
                yield self._create_status_payload(
                    run_id, tool_name, f"Querying search engine: '{query_val}'..."
                )

                query_str = query_val.replace(" ", "+")
                serp_url = f"https://html.duckduckgo.com/html/?q={query_str}"

                raw_serp = await asyncio.to_thread(
                    self.project_david_client.tools.web_read,
                    url=serp_url,
                    force_refresh=True,
                )

                # CRASH FIX: Catch None return
                if raw_serp is None:
                    raw_serp = ""  # _parse_serp_results handles empty string

                yield self._create_status_payload(
                    run_id, tool_name, "Parsing search results..."
                )
                final_content = self._parse_serp_results(raw_serp, query_val)

            else:
                raise ValueError(f"Unknown web tool: {tool_name}")

            # --- [4] RESULT ANALYSIS ---
            # Safety check for None in final_content before iteration
            if final_content is None:
                final_content = "❌ Error: Tool execution returned no data."

            is_soft_failure = (
                "❌ Error" in final_content or "Error:" in final_content[0:50]
            )

            if is_soft_failure:
                yield self._create_status_payload(
                    run_id,
                    tool_name,
                    "Encountered external error (processing)...",
                    state="warning",
                )
                final_content = self._format_web_tool_error(
                    tool_name, final_content, arguments_dict
                )
            else:
                yield self._create_status_payload(
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
                "[%s] %s completed in %.2fs (action=%s)",
                run_id,
                tool_name,
                asyncio.get_event_loop().time() - ts_start,
                action.id,
            )

        except Exception as exc:
            # --- [7] HARD FAILURE HANDLING ---
            LOG.error(f"[%s] %s HARD FAILURE: {exc}", run_id, tool_name)

            yield self._create_status_payload(
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
            except Exception as inner:
                LOG.exception("Critical failure during error surfacing: %s", inner)

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
