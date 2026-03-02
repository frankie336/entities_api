# src/api/entities_api/orchestration/mixins/file_search_mixin.py
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional

from projectdavid_common import ToolValidator
from projectdavid_common.validation import StatusEnum

from src.api.entities_api.services.logging_service import LoggingUtility

LOG = LoggingUtility()


class FileSearchMixin:
    """
    Drive the **file_search** tool-call asynchronously.

    Level 2 Enhancement: Implementation of automated self-correction for
    retrieval failures, empty search results, and schema validation.

    Level 3 Enhancement: Fans out across all vector_store_ids declared in
    assistant.tool_resources["file_search"], aggregating results into a
    single ranked list. Hard-fails (with LLM-surfaced hint) if no stores
    are configured.
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

    @staticmethod
    def _format_tool_resources_error(query: str) -> str:
        """
        Returns a clear, actionable hard-failure hint for the LLM when no
        vector stores are resolvable from assistant.tool_resources.
        """
        return (
            f"File Search Result for '{query}': Configuration Error — "
            "No vector stores are associated with this assistant.\n\n"
            "This means the assistant's 'tool_resources' field either missing, empty, "
            "or does not contain a valid 'file_search.vector_store_ids' list.\n\n"
            "Instructions: Inform the user that file search is currently unavailable because "
            "no document store has been linked to this assistant. They should upload files and "
            "attach a vector store to the assistant before retrying this operation."
        )

    async def _resolve_vector_store_ids(self, assistant_id: str) -> list[str]:
        """
        Resolves the list of vector store IDs from the assistant cache's
        tool_resources field.

        Returns an empty list if nothing is configured — callers are responsible
        for treating that as a hard failure.
        """
        try:
            config = await self.assistant_cache.retrieve(assistant_id)
            tool_resources: dict = config.get("tool_resources") or {}
            ids: list = tool_resources.get("file_search", {}).get(
                "vector_store_ids", []
            )
            return [vid for vid in ids if vid]  # strip any None/empty strings
        except Exception as exc:
            LOG.error(
                "FileSearch ▸ Failed to resolve tool_resources for assistant %s: %s",
                assistant_id,
                exc,
            )
            return []

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

        Fans out across every vector store declared in
        assistant.tool_resources["file_search"]["vector_store_ids"].
        Results are concatenated into a single flat list for the LLM.

        Hard-fails with an LLM-surfaced configuration hint if:
          - tool_resources is absent or malformed
          - vector_store_ids is missing or empty
        """
        ts_start = asyncio.get_event_loop().time()

        # --- [L2] SHARED INPUT VALIDATION ---
        validator = ToolValidator()
        validator.schema_registry = {"file_search": ["query_text"]}

        validation_error = validator.validate_args("file_search", arguments_dict)
        is_valid = validation_error is None

        if not is_valid:
            LOG.warning(f"FileSearch ▸ Validation Failed: {validation_error}")

            try:
                action = await asyncio.to_thread(
                    self.project_david_client.actions.create_action,
                    tool_name="file_search",
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

            error_msg = (
                f"{validation_error}\n"
                "Please provide a valid 'query_text' string for the search."
            )

            await self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                content=error_msg,
                action=action if "action" in locals() else None,
                is_error=True,
            )
            return

        query_text: str = arguments_dict.get("query_text", "")

        # --- [L3] RESOLVE VECTOR STORES FROM tool_resources ---
        vector_store_ids = await self._resolve_vector_store_ids(assistant_id)

        if not vector_store_ids:
            LOG.error(
                "FileSearch ▸ No vector_store_ids found in tool_resources for assistant %s.",
                assistant_id,
            )
            # Create + immediately fail the action so history is consistent
            try:
                action = await asyncio.to_thread(
                    self.project_david_client.actions.create_action,
                    tool_name="file_search",
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
                content=self._format_tool_resources_error(query_text),
                action=action,
                is_error=True,  # Forces LLM correction turn
            )
            return

        # 1. Create Action Record (Success Path)
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
            # 2. Fan out — search every vector store concurrently
            LOG.info(
                "FileSearch ▸ Searching %d vector store(s) for run %s: %s",
                len(vector_store_ids),
                run_id,
                vector_store_ids,
            )

            async def _search_one(
                vid: str,
            ) -> tuple[str, list | None, Exception | None]:
                """Search a single store. Returns (vid, results, error)."""
                try:
                    results = await asyncio.to_thread(
                        self.project_david_client.vectors.unattended_file_search,
                        vector_store_id=vid,
                        query_text=query_text,
                        vector_store_host="qdrant",
                    )
                    return vid, results, None
                except Exception as exc:
                    return vid, None, exc

            outcomes = await asyncio.gather(
                *[_search_one(vid) for vid in vector_store_ids]
            )

            # 3. Aggregate results — concatenate across all stores
            aggregated: list = []
            store_errors: list[str] = []

            for vid, results, exc in outcomes:
                if exc is not None:
                    LOG.error("FileSearch ▸ Store %s raised an exception: %s", vid, exc)
                    store_errors.append(f"Store '{vid}': {exc}")
                elif results:
                    aggregated.extend(results)

            # 4. Determine final outcome
            has_results = len(aggregated) > 0
            is_soft_failure = False

            if not has_results and not store_errors:
                # All stores returned cleanly but found nothing
                is_soft_failure = True
                final_content = self._format_level2_search_error(
                    "No relevant document snippets found across all attached vector stores.",
                    query_text,
                )
                LOG.warning(
                    "FileSearch ▸ No results across %d store(s) for '%s'. "
                    "Triggering self-correction turn.",
                    len(vector_store_ids),
                    query_text,
                )

            elif not has_results and store_errors:
                # Every store threw an exception — hard failure
                error_summary = "\n".join(store_errors)
                is_soft_failure = True  # Still surfaces as a correction turn
                final_content = self._format_level2_search_error(
                    f"All vector store searches failed:\n{error_summary}",
                    query_text,
                )
                LOG.error(
                    "FileSearch ▸ All %d store(s) failed for run %s.",
                    len(vector_store_ids),
                    run_id,
                )

            else:
                # At least some results — surface them, log any partial failures
                if store_errors:
                    LOG.warning(
                        "FileSearch ▸ Partial failure: %d store(s) errored, "
                        "%d result(s) returned. Errors: %s",
                        len(store_errors),
                        len(aggregated),
                        store_errors,
                    )
                final_content = json.dumps(aggregated, indent=2)

            # 5. Submit Tool Output
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
                "[%s] file_search completed in %.2fs (action=%s, stores=%d, results=%d)",
                run_id,
                asyncio.get_event_loop().time() - ts_start,
                action.id,
                len(vector_store_ids),
                len(aggregated),
            )

        except Exception as exc:
            # --- LEVEL 2: HANDLE UNEXPECTED HARD FAILURES ---
            LOG.error(
                "[%s] file_search HARD FAILURE action=%s exc=%s",
                run_id,
                action.id,
                exc,
            )

            error_hint = self._format_level2_search_error(str(exc), query_text)

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
