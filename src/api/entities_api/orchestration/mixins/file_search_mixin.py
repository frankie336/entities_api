# src/api/entities_api/orchestration/mixins/file_search_mixin.py
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional

from projectdavid_common.validation import StatusEnum

from src.api.entities_api.services.logging_service import LoggingUtility

LOG = LoggingUtility()


class FileSearchMixin:
    """
    Drive the **file_search** tool-call asynchronously.

    Level 2 Enhancement: Implementation of automated self-correction for
    retrieval failures and empty search results.
    """

    @staticmethod
    def _format_level2_search_error(error_content: str, query: str) -> str:
        """
        Translates retrieval crashes or empty sets into actionable hints for the LLM.
        """
        return (
            f"File Search Result for '{query}': {error_content}\n\n"
            "Instructions: If no results were found, please try again with broader keywords, "
            "remove specific filters, or check if the document names provided in context exist. "
            "If this was a system error, you may attempt to retry once."
        )

    async def handle_file_search(
        self,
        thread_id: str,
        run_id: str,
        assistant_id: str,
        arguments_dict: Dict[str, Any],
        tool_call_id: Optional[str] = None,
        decision: Optional[Dict] = None,
    ) -> None:
        """
        Asynchronous handler for file_search.
        Signals the internal orchestrator loop for Turn 2 if retrieval fails
        or returns empty results.
        """
        ts_start = asyncio.get_event_loop().time()
        query_text: str = arguments_dict.get("query_text", "")

        # 1. Create Action Record
        try:
            action = await asyncio.to_thread(
                self.project_david_client.actions.create_action,
                tool_name="file_search",
                run_id=run_id,
                tool_call_id=tool_call_id,
                function_args=arguments_dict,
                decision=decision,
            )
        except Exception as e:
            LOG.error(f"FileSearch ▸ Action creation failed for run {run_id}: {e}")
            return

        try:
            # 2. Retrieve Run and User ID (Threaded)
            run = await asyncio.to_thread(
                self.project_david_client.runs.retrieve_run, run_id=run_id
            )
            user_id = run.user_id

            # 3. Vector Store Lookup/Creation (Threaded)
            vector_store_id = await asyncio.to_thread(
                self.project_david_client.vectors.get_or_create_file_search_store,
                user_id=user_id,
            )

            # 4. Perform Search (Heavy I/O - Threaded)
            search_results = await asyncio.to_thread(
                self.project_david_client.vectors.unattended_file_search,
                vector_store_id=vector_store_id,
                query_text=query_text,
                vector_store_host="qdrant",
            )

            # --- LEVEL 2: DETECT EMPTY RESULTS (Soft Failure) ---
            # If search returns nothing, we treat it as an error Turn to force the model to rethink keywords
            is_soft_failure = False
            if not search_results or (
                isinstance(search_results, list) and len(search_results) == 0
            ):
                is_soft_failure = True
                final_content = self._format_level2_search_error(
                    "No relevant document snippets found.", query_text
                )
                LOG.warning(
                    f"FileSearch ▸ No results for '{query_text}'. Triggering self-correction turn."
                )
            else:
                final_content = json.dumps(search_results, indent=2)

            # 5. Submit Tool Output
            # If soft failure, we flag is_error=True to trigger the next Turn in process_conversation
            await self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                content=final_content,
                action=action,
                is_error=is_soft_failure,
            )

            # 6. Mark Action Status
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
                "[%s] file_search completed in %.2fs (action=%s)",
                run_id,
                asyncio.get_event_loop().time() - ts_start,
                action.id,
            )

        except Exception as exc:
            # --- LEVEL 2: HANDLE HARD FAILURES (Crashes) ---
            LOG.error(
                f"[%s] file_search HARD FAILURE action=%s exc=%s",
                run_id,
                action.id,
                exc,
            )

            # Construct a clean instructional hint for the LLM
            error_hint = self._format_level2_search_error(str(exc), query_text)

            try:
                # Update status (Threaded)
                await asyncio.to_thread(
                    self.project_david_client.actions.update_action,
                    action_id=action.id,
                    status=StatusEnum.failed.value,
                )

                # Surface the error as a correction turn
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
