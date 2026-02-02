from __future__ import annotations

import asyncio
import json
import os
import time
import traceback
from typing import Any, Dict, Optional

import httpx
from projectdavid_common.validation import StatusEnum

from src.api.entities_api.services.logging_service import LoggingUtility

LOG = LoggingUtility()

SURFACE_TRACEBACK = os.getenv("SURFACE_TRACEBACK", "false").lower() == "true"


class FileSearchMixin:
    """
    Drive the **file_search** tool-call asynchronously:

    • creates/updates the Action record
    • looks up (or lazily creates) the caller’s “file_search” vector-store
    • runs an unattended_vector search and submits results back to the thread
    • offloads blocking sync I/O to background threads
    """

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
        Uses asyncio.to_thread to prevent Qdrant/DB lookups from blocking the event loop.
        """
        ts_start = asyncio.get_event_loop().time()

        # 1. Create Action Record (Offloaded to thread with keyword safety)
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

        LOG.debug(
            "[%s] Created action id=%s args=%s",
            run_id,
            action.id,
            json.dumps(arguments_dict),
        )

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

            query_text: str = arguments_dict.get("query_text", "")
            LOG.debug(
                "[%s] file_search → store=%s query=%s",
                run_id,
                vector_store_id,
                query_text,
            )

            # 4. Perform Search (Heavy I/O - Threaded)
            search_results = await asyncio.to_thread(
                self.project_david_client.vectors.unattended_file_search,
                vector_store_id=vector_store_id,
                query_text=query_text,
                vector_store_host="qdrant",
            )

            LOG.debug("[%s] file_search results received", run_id)

            # 5. Submit Tool Output (Awaiting the now-async handler)
            await self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                content=json.dumps(search_results, indent=2),
                action=action,
            )

            # 6. Mark Action Completed (Threaded)
            await asyncio.to_thread(
                self.project_david_client.actions.update_action,
                action_id=action.id,
                status=StatusEnum.completed.value,
            )

            LOG.info(
                "[%s] file_search completed in %.2fs (action=%s)",
                run_id,
                asyncio.get_event_loop().time() - ts_start,
                action.id,
            )

        except Exception as exc:
            tb = traceback.format_exc()
            LOG.error(
                "[%s] file_search FAILED action=%s exc=%s\n%s",
                run_id,
                action.id,
                exc,
                tb,
            )

            # Update action status to failed (Threaded)
            try:
                await asyncio.to_thread(
                    self.project_david_client.actions.update_action,
                    action_id=action.id,
                    status=StatusEnum.failed.value,
                )
            except:
                pass

            # Construct and surface error block
            err_block = {"error_type": exc.__class__.__name__, "message": str(exc)}
            if isinstance(exc, httpx.HTTPStatusError):
                err_block.update(
                    {
                        "status_code": exc.response.status_code,
                        "response_text": exc.response.text,
                        "url": str(exc.request.url),
                    }
                )
            if SURFACE_TRACEBACK:
                err_block["traceback"] = tb

            try:
                # Surface the error to the assistant so it doesn't hang (Async)
                await self.submit_tool_output(
                    thread_id=thread_id,
                    assistant_id=assistant_id,
                    tool_call_id=tool_call_id,
                    content=json.dumps(err_block, indent=2),
                    action=action,
                    is_error=True,
                )
            except Exception as inner:
                LOG.exception("[%s] Failed to surface error: %s", run_id, inner)

            # We don't necessarily want to crash the whole worker stream,
            # just report the tool failure to the LLM.
