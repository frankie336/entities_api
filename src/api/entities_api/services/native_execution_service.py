import asyncio
import json
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
from src.api.entities_api.services.runs_service import RunService
from src.api.entities_api.services.scratchpad_service import ScratchpadService
from src.api.entities_api.services.threads_service import ThreadService
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
        self.run_svc = RunService()
        self.thread_svc = ThreadService()
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

    @staticmethod
    def _coerce_function_args(function_args: Any) -> Dict[str, Any]:
        """
        Normalise function_args to a plain dict regardless of how the caller
        provided it.

        Callers in the delegation layer receive arguments_dict from the
        platform's tool-call parser, which may hand them a JSON string, an
        already-decoded dict, or None.  ActionCreate requires a dict, so we
        normalise here rather than letting a Pydantic ValidationError propagate
        and leave `action` as None in the caller.
        """
        if function_args is None:
            return {}
        if isinstance(function_args, dict):
            return function_args
        if isinstance(function_args, str):
            try:
                parsed = json.loads(function_args)
                return parsed if isinstance(parsed, dict) else {"raw": function_args}
            except (json.JSONDecodeError, ValueError):
                return {"raw": function_args}
        # Fallback for any other type (int, list, …)
        return {"raw": str(function_args)}

    async def create_action(
        self,
        tool_name: str,
        run_id: str,
        tool_call_id: Optional[str] = None,
        function_args: Optional[Any] = None,
        decision: Optional[Dict] = None,
    ) -> Any:
        """
        Create an action record via the local ActionService.

        function_args is normalised to a dict before validation so that
        callers passing a raw JSON string (as the delegation mixin does) do not
        trigger a Pydantic ValidationError that would leave the caller holding
        a None action object.

        Raises on unrecoverable errors so the caller's existing try/except
        can decide how to handle the failure.
        """
        normalised_args = self._coerce_function_args(function_args)

        req = self.val_interface.ActionCreate(
            tool_name=tool_name,
            run_id=run_id,
            tool_call_id=tool_call_id,
            function_args=normalised_args,
            decision=decision,
        )
        return await asyncio.to_thread(self.action_svc.create_action, req)

    async def update_action_status(self, action_id: str, status: str) -> Any:
        """
        Update only the status field of an action record.

        ActionService.update_action_status also writes action_update.result
        back to the DB.  We deliberately omit result here so that a status-only
        update does not overwrite previously stored result data with None.
        """

        # Build the update payload with an explicit sentinel so ActionService
        # never receives result=None and blindly wipes the stored value.
        # ActionUpdate.result has no default sentinel in the validator, so we
        # pass the current stored value by fetching it first.
        def _update():
            # Fetch the existing action so we can preserve its result field.
            existing = self.action_svc.get_action(action_id)
            req = self.val_interface.ActionUpdate(
                status=status,
                result=existing.result,  # preserve whatever is already stored
            )
            return self.action_svc.update_action_status(action_id, req)

        return await asyncio.to_thread(_update)

    async def create_run(
        self,
        assistant_id: str,
        thread_id: str,
        user_id: str,
        meta_data: Optional[Dict] = None,
    ) -> Any:
        """
        Create a run record via the local RunService, bypassing the HTTP SDK.

        We deliberately avoid val_interface.RunCreate here because the local
        Pydantic model requires id, created_at, expires_at, and instructions as
        mandatory fields — those are all generated or resolved by RunService
        itself and must NOT be supplied by the caller.  The SDK's RunCreate is
        a lighter model that only needs assistant_id + thread_id.

        Instead we pass a SimpleNamespace that satisfies every attribute access
        RunService.create_run performs, using the same fallback logic the method
        applies (None / empty collection where the service falls back to the
        assistant's own values).
        """
        import types

        req = types.SimpleNamespace(
            assistant_id=assistant_id,
            thread_id=thread_id,
            meta_data=meta_data or {},
            # Fields RunService reads with "getattr(..., None)" or "x or assistant.x"
            # — supply None so the service falls back to the assistant's own values.
            model=None,
            instructions=None,
            tools=None,
            temperature=None,
            top_p=None,
            tool_resources=None,
            parallel_tool_calls=True,
            response_format="text",
            truncation_strategy=None,
        )

        def _create():
            return self.run_svc.create_run(req, user_id=user_id)

        return await asyncio.to_thread(_create)

    async def retrieve_run(self, run_id: str):
        return await asyncio.to_thread(self.run_svc.retrieve_run, run_id)

    async def create_thread(self, user_id: str) -> Any:
        """
        Create a thread owned by the given user, bypassing the HTTP SDK.

        The SDK previously passed the admin user as participant, which was
        incorrect.  This method passes the resolved owner user_id so the
        ephemeral thread is correctly associated with the real user who
        triggered the delegation.

        ThreadService.create_thread validates that the participant exists in
        the users table before inserting, so an invalid user_id will raise
        HTTPException(400) rather than producing an orphaned thread.
        """
        import types

        # ThreadService only accesses thread.participant_ids — use a
        # SimpleNamespace to avoid any mandatory-field issues on ThreadCreate.
        req = types.SimpleNamespace(participant_ids=[user_id])
        return await asyncio.to_thread(self.thread_svc.create_thread, req)

    async def create_message(
        self,
        thread_id: str,
        assistant_id: str,
        content: str,
        role: str = "user",
    ) -> Any:
        """
        Create a message on a thread via the local MessageService,
        bypassing the HTTP SDK.

        role defaults to 'user' which matches the delegation flow where the
        supervisor prompt is injected as a user-turn message before the
        ephemeral run is created.
        """
        req = self.val_interface.MessageCreate(
            thread_id=thread_id,
            assistant_id=assistant_id,
            content=content,
            role=role,
        )
        return await asyncio.to_thread(self.message_svc.create_message, req)

    async def delete_thread(self, thread_id: str) -> Any:
        """
        Delete a thread and its messages via the local ThreadService,
        bypassing the HTTP SDK.

        Also invalidates the Redis message cache for the thread (handled
        internally by ThreadService.delete_thread).
        """
        return await asyncio.to_thread(self.thread_svc.delete_thread, thread_id)

    async def get_formatted_messages(self, thread_id: str) -> list:
        """
        Fetch all messages for a thread formatted for LLM consumption.

        Delegates directly to MessageService.get_formatted_messages, bypassing
        the HTTP SDK.  Returns the same List[Dict[str, Any]] shape the SDK
        call produces so all call sites are drop-in replaceable.

        Raises HTTPException(404) if the thread does not exist (propagated
        from MessageService unchanged so callers handle it identically).
        """
        return await asyncio.to_thread(self.message_svc.get_formatted_messages, thread_id)

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
        function_args: Optional[Any] = None,
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
            LOG.error(f"NativeExec ▸ Failed to create/update failure action for {tool_name}: {e}")

        await self.submit_tool_output(
            thread_id=thread_id,
            assistant_id=assistant_id,
            tool_call_id=tool_call_id,
            content=error_message,
            action_id=action_id,
            is_error=True,
        )

    async def update_run_status(self, run_id: str, new_status: str) -> Any:
        """
        Update a run's status via the local RunService, bypassing the HTTP SDK.
        """
        return await asyncio.to_thread(self.run_svc.update_run_status, run_id, new_status)

    async def save_assistant_message_chunk(
        self,
        thread_id: str,
        content: str,
        role: str,
        assistant_id: str,
        sender_id: str,
        is_last_chunk: bool = True,
    ) -> Any:
        """
        Persist an assistant message chunk via the local MessageService,
        bypassing the HTTP SDK.

        is_last_chunk defaults to True — callers in the orchestration layer
        always flush the complete assembled reply in a single call.
        """
        return await asyncio.to_thread(
            self.message_svc.save_assistant_message_chunk,
            thread_id,
            content,
            role,
            assistant_id,
            sender_id,
            is_last_chunk,
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
