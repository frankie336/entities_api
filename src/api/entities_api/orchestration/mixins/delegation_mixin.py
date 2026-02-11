from __future__ import annotations

import asyncio
import json
import os
import re
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

from projectdavid.events import StatusEvent
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from src.api.entities_api.clients.unified_async_client import get_cached_client
from src.api.entities_api.constants.worker import WORKER_TOOLS
from src.api.entities_api.orchestration.instructions.assembler import \
    assemble_instructions
from src.api.entities_api.orchestration.instructions.include_lists import \
    L4_RESEARCH_INSTRUCTIONS
from src.api.entities_api.utils.level3_utils import create_status_payload

LOG = LoggingUtility()


class DelegationMixin:
    """
    Spins up an ephemeral Worker Loop that mimics the Level 3 WebSearchMixin logic.
    """

    # --- LEVEL 3 HELPERS ---
    def _worker_parse_serp(self, raw_md: str, query: str) -> str:
        if not raw_md:
            return f"Error: Search returned no data for '{query}'."
        lines = raw_md.split("\n")
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

    def _worker_inject_pagination(self, content: str, url: str) -> str:
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

    # --- THE WORKER LOOP ---
    async def _run_worker_loop_generator(
        self,
        task: str,
        reqs: str,
        run_id: str,
        result_container: List[str],  # Output variable
    ) -> AsyncGenerator[StatusEvent, None]:

        worker_instructions = assemble_instructions(
            include_keys=L4_RESEARCH_INSTRUCTIONS
        )

        messages = [
            {"role": "system", "content": worker_instructions},
            {"role": "user", "content": f"TASK: {task}\nREQUIREMENTS: {reqs}"},
        ]

        # Debug Log
        try:
            LOG.info(f"🛠️ [WORKER START] Run {run_id} | Task: {task}")
        except Exception:
            pass

        MAX_TURNS = 20

        client = get_cached_client(
            api_key=os.environ.get("TOGETHER_API_KEY"),
            base_url=os.environ.get("TOGETHER_BASE_URL"),
            enable_logging=True,
        )

        worker_model = "Qwen/Qwen2.5-72B-Instruct-Turbo"

        for turn in range(MAX_TURNS):
            accumulated_content = ""
            tool_calls_buffer: Dict[int, Dict] = {}

            try:
                stream_gen = client.stream_chat_completion(
                    model=worker_model,
                    messages=messages,
                    tools=WORKER_TOOLS,
                    tool_choice="auto",
                    max_tokens=4096,  # Prevent 400 Bad Request
                    temperature=0.1,
                )

                async for chunk in stream_gen:
                    if not chunk.get("choices"):
                        continue
                    delta = chunk["choices"][0].get("delta", {})

                    if delta.get("content"):
                        accumulated_content += delta["content"]

                    if delta.get("tool_calls"):
                        for tc_chunk in delta["tool_calls"]:
                            idx = tc_chunk["index"]
                            if idx not in tool_calls_buffer:
                                tool_calls_buffer[idx] = {
                                    "id": "",
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                }
                            if "id" in tc_chunk:
                                tool_calls_buffer[idx]["id"] += tc_chunk["id"]
                            if "function" in tc_chunk:
                                fn = tc_chunk["function"]
                                if "name" in fn:
                                    tool_calls_buffer[idx]["function"]["name"] += fn[
                                        "name"
                                    ]
                                if "arguments" in fn:
                                    tool_calls_buffer[idx]["function"][
                                        "arguments"
                                    ] += fn["arguments"]

            except Exception as e:
                LOG.error(f"Worker Loop LLM Error: {e}")
                result_container.append(f"Worker LLM Error: {e}")
                return

            # Reconstruct Message
            msg_dict = {
                "role": "assistant",
                "content": accumulated_content if accumulated_content else None,
            }

            final_tool_calls = []
            if tool_calls_buffer:
                for i in sorted(tool_calls_buffer.keys()):
                    final_tool_calls.append(tool_calls_buffer[i])
                msg_dict["tool_calls"] = final_tool_calls

            messages.append(msg_dict)

            # Check Result
            if not final_tool_calls:
                result_container.append(accumulated_content)
                return

            yield create_status_payload(
                run_id,
                "delegate_research_task",
                f"Worker is researching... (Turn {turn+1})",
                state="in_progress",
            )

            # Execute Tools
            for tool_call in final_tool_calls:
                fn_name = tool_call["function"]["name"]

                try:
                    fn_args = json.loads(tool_call["function"]["arguments"])
                except json.JSONDecodeError:
                    fn_args = {}

                tool_result = ""

                try:
                    # 1. WEB SEARCH
                    if fn_name == "perform_web_search":
                        q = fn_args.get("query", "")
                        if q:
                            raw = await asyncio.to_thread(
                                self.project_david_client.tools.web_read,
                                url=f"https://html.duckduckgo.com/html/?q={q.replace(' ', '+')}",
                                force_refresh=True,
                            )
                            tool_result = self._worker_parse_serp(raw, q)
                        else:
                            tool_result = "Error: Missing query."

                    # 2. READ PAGE
                    elif fn_name == "read_web_page":
                        url = fn_args.get("url")
                        if url:
                            raw = await asyncio.to_thread(
                                self.project_david_client.tools.web_read, url=url
                            )
                            tool_result = self._worker_inject_pagination(raw, url)
                        else:
                            tool_result = "Error: Missing URL."

                    # 3. SEARCH IN PAGE (The one failing previously)
                    elif fn_name == "search_web_page":
                        # SAFETY CHECK: If model forgot query, handle it gracefully
                        url = fn_args.get("url")
                        query = fn_args.get("query")

                        if url and query:
                            tool_result = await asyncio.to_thread(
                                self.project_david_client.tools.web_search,
                                url=url,
                                query=query,
                            )
                        elif url and not query:
                            # Feedback to the model to correct itself
                            tool_result = "Error: You called 'search_web_page' but forgot the 'query' parameter. Please retry with a specific keyword."
                        else:
                            tool_result = "Error: Missing URL and query."

                    # 4. SCROLL PAGE
                    elif fn_name == "scroll_web_page":
                        raw = await asyncio.to_thread(
                            self.project_david_client.tools.web_scroll,
                            url=fn_args.get("url"),
                            page=fn_args.get("page"),
                        )
                        tool_result = self._worker_inject_pagination(
                            raw, fn_args.get("url")
                        )

                    else:
                        tool_result = "Error: Unknown tool."

                except Exception as e:
                    tool_result = f"Tool Execution Error: {e}"

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": str(tool_result),
                    }
                )

        result_container.append("Worker timed out before finding an answer.")

    # --- HANDLER ---
    async def handle_delegate_research_task(
        self,
        thread_id: str,
        run_id: str,
        assistant_id: str,
        arguments_dict: Dict,
        tool_call_id: str,
        decision: Dict,
    ) -> AsyncGenerator[StatusEvent, None]:

        task = arguments_dict.get("task")
        reqs = arguments_dict.get("requirements", "")
        tool_name = "delegate_research_task"

        yield create_status_payload(
            run_id, tool_name, "Delegating task to Worker...", state="in_progress"
        )

        action = None
        try:
            action = await asyncio.to_thread(
                self.project_david_client.actions.create_action,
                tool_name=tool_name,
                run_id=run_id,
                tool_call_id=tool_call_id,
                function_args=arguments_dict,
                decision=decision,
            )
        except Exception:
            pass

        result_container = []
        async for event in self._run_worker_loop_generator(
            task, reqs, run_id, result_container
        ):
            yield event

        final_output = (
            result_container[0] if result_container else "Worker failed silently."
        )

        yield create_status_payload(
            run_id, tool_name, "Worker task complete.", state="success"
        )

        if action:
            await asyncio.to_thread(
                self.project_david_client.actions.update_action,
                action_id=action.id,
                status=StatusEnum.completed.value,
            )

        await self.submit_tool_output(
            thread_id=thread_id,
            assistant_id=assistant_id,
            tool_call_id=tool_call_id,
            content=final_output,
            action=action,
        )
