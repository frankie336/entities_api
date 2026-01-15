from __future__ import annotations

import json
import os
import time
import traceback
from typing import Any, Dict

import httpx
from projectdavid import Entity
from projectdavid_common.validation import StatusEnum

from src.api.entities_api.services.logging_service import LoggingUtility

LOG = LoggingUtility()
client = Entity(
    base_url=os.getenv("BASE_URL", "http://localhost:9000"),
    api_key=os.getenv("ADMIN_API_KEY"),
)
SURFACE_TRACEBACK = os.getenv("SURFACE_TRACEBACK", "false").lower() == "true"


class FileSearchMixin:
    """
    Drive the **file_search** tool-call:

    • creates/updates the Action record
    • looks up (or lazily creates) the caller’s “file_search” vector-store
    • runs an unattended_vector search and streams results back to the thread
    • surfaces readable error blocks instead of hard-crashing the run
    """

    def handle_file_search(
        self,
        thread_id: str,
        run_id: str,
        assistant_id: str,
        arguments_dict: Dict[str, Any],
    ) -> None:
        ts_start = time.perf_counter()
        action = client.actions.create_action(
            tool_name="file_search", run_id=run_id, function_args=arguments_dict
        )
        LOG.debug(
            "[%s] Created action id=%s args=%s",
            run_id,
            action.id,
            json.dumps(arguments_dict, indent=2),
        )
        try:
            run = client.runs.retrieve_run(run_id=run_id)
            user_id = run.user_id
            vector_store_id = client.vectors.get_or_create_file_search_store(
                user_id=user_id
            )
            query_text: str = arguments_dict["query_text"]
            LOG.debug(
                "[%s] file_search → store=%s  query=%s",
                run_id,
                vector_store_id,
                query_text,
            )
            search_results = client.vectors.unattended_file_search(
                vector_store_id=vector_store_id,
                query_text=query_text,
                vector_store_host="qdrant",
            )
            LOG.debug(
                "[%s] file_search raw-hits bytes=%d",
                run_id,
                len(json.dumps(search_results)),
            )
            self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                content=json.dumps(search_results, indent=2),
                action=action,
            )
            self.project_david_client.actions.update_action(
                action_id=action.id, status=StatusEnum.completed
            )
            LOG.info(
                "[%s] file_search completed in %.2fs (action=%s)",
                run_id,
                time.perf_counter() - ts_start,
                action.id,
            )
        except Exception as exc:
            tb = traceback.format_exc()
            LOG.error(
                "[%s] file_search FAILED action=%s  exc=%s\n%s",
                run_id,
                action.id,
                exc,
                tb,
            )
            self.project_david_client.actions.update_action(
                action_id=action.id, status=StatusEnum.failed
            )
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
                self.submit_tool_output(
                    thread_id=thread_id,
                    assistant_id=assistant_id,
                    content=json.dumps(err_block, indent=2),
                    action=action,
                )
            except Exception as inner:
                LOG.exception("[%s] Failed to surface error: %s", run_id, inner)
            raise
