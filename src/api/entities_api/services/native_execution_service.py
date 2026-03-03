# src/api/entities_api/services/native_execution_service.py
import asyncio
from typing import Any, Dict, Optional

from projectdavid_common import ValidationInterface
from projectdavid_common.validation import StatusEnum

from src.api.entities_api.cache.scratchpad_cache import ScratchpadCache
from src.api.entities_api.cache.web_cache import WebSessionCache
from src.api.entities_api.db.database import SessionLocal
from src.api.entities_api.dependencies import get_redis_sync
from src.api.entities_api.services.actions_service import ActionService
from src.api.entities_api.services.logging_service import LoggingUtility
from src.api.entities_api.services.message_service import MessageService
from src.api.entities_api.services.scratchpad_service import ScratchpadService
from src.api.entities_api.services.vectors_service import VectorStoreDBService
from src.api.entities_api.services.web_reader import UniversalWebReader

LOG = LoggingUtility()


class NativeExecutionService:
    """
    Helper service to manage native database executions, bypassing the HTTP SDK.

    Provides async-friendly wrappers around:
      - Action and Message operations          (create, update, submit)
      - Vector store lookups                   (get_vector_store)
      - Web reading and SERP search            (read_url, scroll_url,
                                                search_url, serp_search)

    All web-reader calls are routed through UniversalWebReader, which offloads
    network I/O to the remote browserless/chromium container so this service
    stays secure and lightweight.
    """

    def __init__(self):
        self.action_svc = ActionService()
        self.message_svc = MessageService()
        self.val_interface = ValidationInterface()

        redis = get_redis_sync()

        self.scratchpad_svc = ScratchpadService(cache=ScratchpadCache(redis=redis))

        # Web reader — shares the same Redis instance for its session cache
        self.web_reader = UniversalWebReader(cache_service=WebSessionCache(redis=redis))

    # ------------------------------------------------------------------
    # Vector Store
    # ------------------------------------------------------------------

    async def get_vector_store(self, vector_store_id: str) -> Any:
        def _fetch():
            with SessionLocal() as db:
                svc = VectorStoreDBService(db)
                return svc.get_vector_store_by_id(vector_store_id)

        return await asyncio.to_thread(_fetch)

    # ------------------------------------------------------------------
    # Action / Message Operations
    # ------------------------------------------------------------------

    async def create_action(
        self,
        tool_name: str,
        run_id: str,
        tool_call_id: Optional[str] = None,
        function_args: Optional[Dict[str, Any]] = None,
        decision: Optional[Dict] = None,
    ) -> Any:
        req = self.val_interface.ActionCreate(
            tool_name=tool_name,
            run_id=run_id,
            tool_call_id=tool_call_id,
            function_args=function_args or {},
            decision=decision,
        )
        return await asyncio.to_thread(self.action_svc.create_action, req)

    async def update_action_status(self, action_id: str, status: str) -> Any:
        req = self.val_interface.ActionUpdate(status=status)
        return await asyncio.to_thread(
            self.action_svc.update_action_status, action_id, req
        )

    async def submit_tool_output(
        self,
        thread_id: str,
        assistant_id: str,
        tool_call_id: Optional[str],
        content: str,
        action_id: Optional[str] = None,
        is_error: bool = False,
    ) -> Any:
        msg_req = self.val_interface.MessageCreate(
            thread_id=thread_id,
            assistant_id=assistant_id,
            role="tool",
            content=content,
            tool_call_id=tool_call_id,
            meta_data={"action_id": action_id, "is_error": is_error},
        )
        return await asyncio.to_thread(self.message_svc.submit_tool_output, msg_req)

    async def submit_failed_tool_execution(
        self,
        tool_name: str,
        run_id: str,
        thread_id: str,
        assistant_id: str,
        tool_call_id: Optional[str],
        error_message: str,
        function_args: Optional[Dict[str, Any]] = None,
        decision: Optional[Dict] = None,
    ) -> None:
        action_id = None
        try:
            action = await self.create_action(
                tool_name=tool_name,
                run_id=run_id,
                tool_call_id=tool_call_id,
                function_args=function_args,
                decision=decision,
            )
            action_id = action.id
            await self.update_action_status(action_id, StatusEnum.failed.value)
        except Exception as e:
            LOG.error(
                f"NativeExec ▸ Failed to create/update failure action for {tool_name}: {e}"
            )

        await self.submit_tool_output(
            thread_id=thread_id,
            assistant_id=assistant_id,
            tool_call_id=tool_call_id,
            content=error_message,
            action_id=action_id,
            is_error=True,
        )

    # ------------------------------------------------------------------
    # Web Reader — native wrappers (no SDK, no HTTP round-trip)
    # ------------------------------------------------------------------

    async def read_url(self, url: str, force_refresh: bool = False) -> str:
        """
        Scrape a URL via the remote browserless container.

        Checks Redis first; only hits the browser service on a cache miss
        (or when force_refresh=True).  Returns page 0 of the chunked content.

        Args:
            url:           The target URL to fetch.
            force_refresh: Bypass the cache and re-fetch unconditionally.

        Returns:
            Markdown-formatted page content (first chunk / page 0).
        """
        LOG.info(f"NativeExec ▸ read_url: {url} (force_refresh={force_refresh})")
        return await self.web_reader.read(url, force_refresh=force_refresh)

    async def scroll_url(self, url: str, page: int) -> str:
        """
        Return a specific page of a previously cached URL.

        The URL must have been fetched with read_url first; scroll_url operates
        entirely from Redis and never hits the browser service.

        Args:
            url:  The previously-fetched URL.
            page: Zero-based page index into the cached chunks.

        Returns:
            The requested chunk as a Markdown string, or an appropriate
            cache-miss message if the session doesn't exist yet.
        """
        LOG.info(f"NativeExec ▸ scroll_url: {url} page={page}")
        return await self.web_reader.scroll(url, page)

    async def search_url(self, url: str, query: str) -> str:
        """
        Full-text search within the cached content of a URL.

        Searches the Redis-stored session for the given URL.  The URL must have
        been fetched with read_url first.

        Args:
            url:   The previously-fetched URL whose cache will be searched.
            query: The search term(s) to look for.

        Returns:
            Relevant excerpts as a Markdown string.
        """
        LOG.info(f"NativeExec ▸ search_url: '{query}' in {url}")
        return await self.web_reader.search(url, query)

    async def serp_search(self, query: str) -> str:
        """
        Perform a live DuckDuckGo SERP search via the browser service.

        Results are always force-refreshed (no caching of SERP pages) and
        returned as a numbered Markdown list of titles + URLs, ready for the
        agent to decide which to read_url next.

        Args:
            query: The search query string.

        Returns:
            A formatted Markdown string with up to 5 results and a system
            hint directing the agent to call read_url on chosen links.
        """
        LOG.info(f"NativeExec ▸ serp_search: '{query}'")
        return await self.web_reader.perform_serp_search(query)
