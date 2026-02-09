# src/api/entities_api/orchestration/mixins/web_search_mixin.py
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, Optional

from projectdavid_common import ToolValidator
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

LOG = LoggingUtility()


class WebSearchMixin:
    """
    Drive the **Level 3 Agentic Web Tools** (read, scroll, search, discovery).

    Features:
    1. **Discovery (SERP)**: Finds URLs via DuckDuckGo.
    2. **Smart Navigation**: Injects next-page logic into read results.
    3. **Resilient Error Handling**: Translates HTTP errors into agent instructions.
    """

    @staticmethod
    def _format_web_tool_error(tool_name: str, error_content: str, inputs: Dict) -> str:
        """
        Translates web failures into actionable Level 2 instructions for the LLM.
        """
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
        This forces the model to see the 'Next Step' immediately after the data.
        """
        # Regex to find "Page X of Y" (Matches: "Page 0 of 5", "Page 1 / 10")
        page_match = re.search(
            r"Page\s+(\d+)\s*(?:of|/)\s*(\d+)", content, re.IGNORECASE
        )

        if not page_match:
            # Fallback for pages without clear pagination
            return content + (
                "\n\n--- 🧭 NAVIGATION HINT ---\n"
                "If the answer is not visible above, use `search_web_page(url=..., query='...')` "
                "to find specific keywords."
            )

        current_page = int(page_match.group(1))
        total_pages = int(page_match.group(2))
        next_page = current_page + 1

        if current_page >= total_pages - 1:
            return (
                content
                + "\n\n--- ✅ END OF DOCUMENT ---\n(No further scrolling possible. Synthesize your findings.)"
            )

        footer = (
            f"\n\n--- 🧭 LEVEL 3 NAVIGATION PANEL (Current: Page {current_page} of {total_pages}) ---\n"
            f"The document continues. Choose your next move based on the protocol:\n\n"
            f"1. **TARGETED SEARCH (Recommended):**\n"
            f"   If you are looking for specific facts, DO NOT SCROLL. Use:\n"
            f"   `search_web_page(url='{url}', query='<keyword>')`\n\n"
            f"2. **SEQUENTIAL READING:**\n"
            f"   If reading a narrative/story, fetch the next segment using:\n"
            f"   `scroll_web_page(url='{url}', page={next_page})`"
        )
        return content + footer

    def _parse_serp_results(self, raw_markdown: str, query: str) -> str:
        """
        Parses raw markdown from a SERP (DuckDuckGo HTML) into a clean list of URLs.
        Includes a failsafe prompt if parsing fails (e.g. CAPTCHA).
        """
        lines = raw_markdown.split("\n")
        results = []
        count = 0

        # Heuristic parser for DDG HTML results converted to Markdown
        for line in lines:
            if count >= 5:
                break
            # Look for lines that contain a markdown link [Title](URL)
            # Filter out internal DDG links
            if "](" in line and "duckduckgo.com" not in line:
                match = re.search(r"\((https?://[^)]+)\)", line)
                if match:
                    url = match.group(1)
                    # Clean title: [Title] -> Title
                    title = line.split("](")[0].strip("[")
                    results.append(f"{count+1}. **{title}**\n   LINK: {url}")
                    count += 1

        if not results:
            # FAILSAFE: If parsing failed, the page might be a CAPTCHA or raw HTML error.
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
    ) -> None:
        """
        Shared core logic for Read, Scroll, Search, and SERP (Global Search).
        """
        ts_start = asyncio.get_event_loop().time()

        # --- [1] VALIDATION ---
        validator = ToolValidator()
        validator.schema_registry = {tool_name: required_keys}
        validation_error = validator.validate_args(tool_name, arguments_dict)

        if validation_error:
            LOG.warning(f"{tool_name} ▸ Validation Failed: {validation_error}")
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
                action = None

            await self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                content=f"Schema Validation Error: {validation_error}",
                action=action,
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
            LOG.error(f"{tool_name} ▸ Action creation failed: {e}")
            return

        # --- [3] EXECUTION (Threaded I/O) ---
        try:
            final_content = ""

            # --- A. READ PAGE ---
            if tool_name == "read_web_page":
                target_url = arguments_dict["url"]
                raw_content = await asyncio.to_thread(
                    self.project_david_client.tools.web_read,
                    url=target_url,
                    force_refresh=arguments_dict.get("force_refresh", False),
                )
                final_content = self._inject_navigation_guidance(
                    raw_content, target_url
                )

            # --- B. SCROLL PAGE ---
            elif tool_name == "scroll_web_page":
                target_url = arguments_dict["url"]
                raw_content = await asyncio.to_thread(
                    self.project_david_client.tools.web_scroll,
                    url=target_url,
                    page=arguments_dict["page"],
                )
                final_content = self._inject_navigation_guidance(
                    raw_content, target_url
                )

            # --- C. INTERNAL SEARCH (Ctrl+F) ---
            elif tool_name == "search_web_page":
                target_url = arguments_dict["url"]
                final_content = await asyncio.to_thread(
                    self.project_david_client.tools.web_search,
                    url=target_url,
                    query=arguments_dict["query"],
                )

            # --- D. GLOBAL SEARCH (SERP) ---
            elif tool_name == "perform_web_search":
                # Uses the existing 'web_read' capability to query DuckDuckGo HTML
                query_str = arguments_dict["query"].replace(" ", "+")
                serp_url = f"https://html.duckduckgo.com/html/?q={query_str}"

                # We use force_refresh=True for SERP to avoid stale search results
                raw_serp = await asyncio.to_thread(
                    self.project_david_client.tools.web_read,
                    url=serp_url,
                    force_refresh=True,
                )
                final_content = self._parse_serp_results(
                    raw_serp, arguments_dict["query"]
                )

            else:
                raise ValueError(f"Unknown web tool: {tool_name}")

            # --- [4] RESULT ANALYSIS ---
            is_soft_failure = (
                "❌ Error" in final_content or "Error:" in final_content[0:50]
            )

            if is_soft_failure:
                final_content = self._format_web_tool_error(
                    tool_name, final_content, arguments_dict
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
    ) -> None:
        """Handler for 'perform_web_search' (Google/DDG Discovery)."""
        await self._execute_web_tool_logic(
            tool_name="perform_web_search",
            required_keys=["query"],
            thread_id=thread_id,
            run_id=run_id,
            assistant_id=assistant_id,
            arguments_dict=arguments_dict,
            tool_call_id=tool_call_id,
            decision=decision,
        )

    async def handle_read_web_page(
        self,
        thread_id: str,
        run_id: str,
        assistant_id: str,
        arguments_dict: Dict[str, Any],
        tool_call_id: Optional[str] = None,
        decision: Optional[Dict] = None,
    ) -> None:
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
