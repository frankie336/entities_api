# src/api/entities_api/orchestration/mixins/web_search_mixin.py
from __future__ import annotations

import asyncio
import re
from collections import defaultdict
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

    Features:
    - Lazy-loaded session state (crash-proof).
    - Query Tiering (adjusts research depth based on complexity).
    - Navigation Guidance (detects pagination).
    - SERP Quality Analysis.
    """

    # ------------------------------------------------------------------
    # 1. BULLETPROOF STATE MANAGEMENT (Lazy Load)
    # ------------------------------------------------------------------
    @property
    def _research_sessions(self) -> Dict[str, Dict[str, Any]]:
        """
        Safely retrieves the session store.
        If 'OrchestratorCore' didn't initialize it, we do it ourselves here.
        This prevents 'AttributeError' in complex Mixin hierarchies.
        """
        if not hasattr(self, "_internal_sessions_storage"):
            self._internal_sessions_storage = defaultdict(
                lambda: {
                    "sources_read": 0,
                    "urls_visited": set(),
                    "query_tier": None,
                    "search_performed": False,
                    "initial_query": None,
                }
            )
        return self._internal_sessions_storage

    # ------------------------------------------------------------------
    # 2. HELPER METHODS & LOGIC
    # ------------------------------------------------------------------

    def _classify_query_tier(self, query: str) -> int:
        """
        Classifies query complexity to determine required source count.

        Returns:
            1: Simple factual query (2 sources)
            2: Moderate multi-faceted query (3-4 sources)
            3: Complex analytical query (5-6 sources)
        """
        query_lower = query.lower()

        # Tier 3 indicators: comparison, analysis, "why", "how do X differ"
        tier_3_keywords = [
            "compare",
            "difference",
            "why",
            "analyze",
            "trend",
            "versus",
            "vs",
            "impact of",
            "how do",
            "what are the effects",
        ]
        if any(keyword in query_lower for keyword in tier_3_keywords):
            return 3

        # Tier 2 indicators: multi-part questions, "what are", lists
        tier_2_keywords = [
            "what are",
            "list",
            "benefits",
            "advantages",
            "disadvantages",
            "types of",
            "examples of",
            "methods",
            "ways to",
        ]
        if any(keyword in query_lower for keyword in tier_2_keywords):
            return 2

        # Tier 1: Simple factual queries
        return 1

    def _get_or_create_session(
        self, run_id: str, query: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get or initialize research session for this run safely."""
        # Access via the property to ensure it exists
        session = self._research_sessions[run_id]

        if query and session["query_tier"] is None:
            session["query_tier"] = self._classify_query_tier(query)
            session["initial_query"] = query
            LOG.info(
                f"[{run_id}] Query classified as Tier {session['query_tier']}: {query}"
            )

        return session

    async def _validate_research_completeness(
        self,
        run_id: str,
        session: Optional[Dict[str, Any]] = None,
    ) -> tuple[bool, str]:
        """
        Validates if research meets quality standards.
        Useful for internal checks even if not blocking the orchestrator.
        """
        if session is None:
            # Use safe get logic
            if run_id not in self._research_sessions:
                return True, "No active research session"
            session = self._research_sessions[run_id]

        query_tier = session.get("query_tier", 1)
        sources_read = session.get("sources_read", 0)
        search_performed = session.get("search_performed", False)

        min_sources = {1: 2, 2: 3, 3: 5}
        required = min_sources.get(query_tier, 2)

        # Check if search was even performed
        if not search_performed:
            return True, "No web search performed, skipping validation"

        # Check source count
        if sources_read < required:
            shortage = required - sources_read
            return False, (
                f"⚠️ RESEARCH INCOMPLETE: Tier {query_tier} query requires {required} sources.\n"
                f"Currently read: {sources_read} source(s).\n"
                f"ACTION REQUIRED: Read {shortage} more source(s) before providing final answer."
            )

        return True, f"Research complete: {sources_read}/{required} sources read."

    def _clear_session(self, run_id: str):
        """Clear research session after completion."""
        if run_id in self._research_sessions:
            del self._research_sessions[run_id]

    @staticmethod
    def _format_web_tool_error(tool_name: str, error_content: str, inputs: Dict) -> str:
        """Translates failures into actionable instructions."""
        if not error_content:
            error_content = "Unknown Error (Empty Response)"

        error_lower = error_content.lower()

        # --- 1. SCHEMA/VALIDATION RECOVERY ---
        if "validation error" in error_lower or "missing arguments" in error_lower:
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

        return (
            f"❌ Web Tool '{tool_name}' Error: {error_content}\n"
            "SYSTEM INSTRUCTION: Review arguments. If error persists, stop using this tool."
        )

    def _inject_navigation_guidance(self, content: str, url: str) -> str:
        """Injects hints if content looks like a paginated document."""
        if not content:
            return ""

        # Regex to find "Page X of Y" or "Page X/Y"
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

    def _parse_serp_results(self, raw_markdown: str, query: str, run_id: str) -> str:
        """Enhanced SERP parsing with quality hints and progress tracking."""
        if not raw_markdown:
            return f"Error: No data for '{query}'."

        # Update session
        session = self._get_or_create_session(run_id, query)
        session["search_performed"] = True

        lines = raw_markdown.split("\n")
        results = []
        count = 0

        for line in lines:
            if count >= 10:  # Limit results to keep context clean
                break
            # Parsing logic for markdown links [Title](URL)
            if "](" in line and "duckduckgo" not in line:
                match = re.search(r"\((https?://[^)]+)\)", line)
                if match:
                    title = line.split("](")[0].strip("[")
                    url = match.group(1)

                    # Add source quality hints
                    quality_hint = ""
                    if any(domain in url for domain in [".gov", ".edu", ".org"]):
                        quality_hint = " [HIGH AUTHORITY]"
                    elif "wikipedia.org" in url:
                        quality_hint = " [ENCYCLOPEDIA]"

                    results.append(
                        f"{count+1}. **{title}**{quality_hint}\n   URL: {url}"
                    )
                    count += 1

        if not results:
            return "No results found."

        # Determine required sources based on tier
        query_tier = session["query_tier"]
        min_sources = {1: 2, 2: 3, 3: 5}.get(query_tier, 3)

        output = (
            f"🔍 SEARCH RESULTS for '{query}' ({count} found):\n"
            f"📊 Query Classification: Tier {query_tier} (Requires {min_sources} sources)\n\n"
            + "\n".join(results)
        )

        # Add mandatory next-step instruction
        output += (
            f"\n\n⚠️ MANDATORY NEXT ACTION:\n"
            f"You MUST call read_web_page on at least {min_sources} results above.\n"
            f"Current progress: 0/{min_sources} sources read.\n"
            f"SERP snippets alone are NOT sufficient for answering this query.\n"
            f"Recommended: Read top {min(min_sources + 1, count)} URLs to ensure quality."
        )

        return output

    # ------------------------------------------------------------------
    # 3. CORE EXECUTION LOGIC (The Engine)
    # ------------------------------------------------------------------

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
        Shared core logic for Read, Scroll, Search, and SERP with progress tracking.
        """
        ts_start = asyncio.get_event_loop().time()

        # --- [1] STATUS: VALIDATING ---
        yield create_status_payload(run_id, tool_name, "Validating parameters...")

        # --- VALIDATION ---
        validator = ToolValidator()
        validator.schema_registry = {tool_name: required_keys}
        validation_error = validator.validate_args(tool_name, arguments_dict)

        if validation_error:
            LOG.warning(f"{tool_name} ▸ Validation Failed: {validation_error}")
            yield create_status_payload(
                run_id, tool_name, "Validation failed.", state="error"
            )

            error_feedback = self._format_web_tool_error(
                tool_name, f"Validation Error: {validation_error}", arguments_dict
            )

            # Submit error to DB and LLM
            try:
                action = await asyncio.to_thread(
                    self.project_david_client.actions.create_action,
                    tool_name=tool_name,
                    run_id=run_id,
                    tool_call_id=tool_call_id,
                    function_args=arguments_dict,
                    decision=decision,
                )

                await self.submit_tool_output(
                    thread_id=thread_id,
                    assistant_id=assistant_id,
                    tool_call_id=tool_call_id,
                    content=error_feedback,
                    action=action,
                    is_error=True,
                )

                await asyncio.to_thread(
                    self.project_david_client.actions.update_action,
                    action_id=action.id,
                    status=StatusEnum.failed.value,
                )
            except Exception as e:
                LOG.error(f"Failed to submit validation error: {e}")

            return

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

            if tool_name == "read_web_page":
                target_url = arguments_dict["url"]
                yield create_status_payload(
                    run_id, tool_name, f"Reading: {target_url}..."
                )

                # Track source reading
                session = self._get_or_create_session(run_id)
                if target_url not in session["urls_visited"]:
                    session["urls_visited"].add(target_url)
                    session["sources_read"] += 1

                    LOG.info(
                        f"[{run_id}] Progress: {session['sources_read']} sources read "
                        f"(Tier {session.get('query_tier', 'N/A')} query)"
                    )

                raw_content = await asyncio.to_thread(
                    self.project_david_client.tools.web_read,
                    url=target_url,
                    force_refresh=arguments_dict.get("force_refresh", False),
                )

                # Add progress indicator to content
                tier = session.get("query_tier", 1)
                min_sources = {1: 2, 2: 3, 3: 5}.get(tier, 2)
                progress_note = (
                    f"\n\n📊 RESEARCH PROGRESS: {session['sources_read']}/{min_sources} sources read "
                    f"(Tier {tier} query)"
                )

                final_content = (
                    self._inject_navigation_guidance(raw_content, target_url)
                    + progress_note
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
                final_content = self._parse_serp_results(raw_serp, query_val, run_id)

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
            LOG.error(f"[{run_id}] {tool_name} HARD FAILURE: {exc}")
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
    # 4. PUBLIC HANDLERS
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
