import asyncio
import json
from typing import Any, Dict, List, Optional

from projectdavid_common import ValidationInterface
from projectdavid_common.validation import StatusEnum

from src.api.entities_api.cache.scratchpad_cache import ScratchpadCache
from src.api.entities_api.cache.web_cache import WebSessionCache
from src.api.entities_api.db.database import SessionLocal
from src.api.entities_api.dependencies import get_redis_sync
from src.api.entities_api.services.actions_service import ActionService
from src.api.entities_api.services.assistants_service import AssistantService
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
      - Assistant CRUD                         (create_assistant, retrieve_assistant,
                                                delete_assistant)
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
        self.assistant_svc = AssistantService()
        self.run_svc = RunService()
        self.thread_svc = ThreadService()
        self.message_svc = MessageService()
        self.val_interface = ValidationInterface()

        redis = get_redis_sync()

        self.scratchpad_svc = ScratchpadService(cache=ScratchpadCache(redis=redis))
        self.web_reader = UniversalWebReader(cache_service=WebSessionCache(redis=redis))

    async def assert_assistant_access(
        self,
        assistant_id: str,
        user_id: str,
    ) -> None:
        """
        Verifies the user owns or is shared on the assistant.
        Closes the attack vector: valid user + known assistant_id they don't own.

        Raises HTTPException 403 if access denied.
        Raises HTTPException 404 if assistant not found.
        """
        from fastapi import HTTPException

        from src.api.entities_api.models.models import Assistant

        def _check():
            with SessionLocal() as db:
                assistant = (
                    db.query(Assistant)
                    .filter(
                        Assistant.id == assistant_id,
                        Assistant.deleted_at.is_(None),
                    )
                    .first()
                )

                if not assistant:
                    raise HTTPException(status_code=404, detail="Assistant not found.")

                is_owner = assistant.owner_id == user_id
                is_shared = any(u.id == user_id for u in assistant.users)

                if not is_owner and not is_shared:
                    LOG.warning(
                        "[ACCESS GUARD] User %s attempted inference against assistant %s owned by %s",
                        user_id,
                        assistant_id,
                        assistant.owner_id,
                    )
                    raise HTTPException(
                        status_code=403, detail="You do not have access to this assistant."
                    )

        await asyncio.to_thread(_check)

    # ------------------------------------------------------------------
    # Assistant
    # ------------------------------------------------------------------
    async def create_assistant(
        self,
        user_id: str,
        name: str,
        model: str = "gpt-oss-120b",
        description: str = "",
        instructions: str = "",
        tools: Optional[List] = None,
        tool_resources: Optional[Dict] = None,
        meta_data: Optional[Dict] = None,
        web_access: bool = False,
        deep_research: bool = False,
        engineer: bool = False,
        agent_mode: bool = False,
        decision_telemetry: bool = False,
        max_turns: int = 1,
        temperature: Optional[float] = None,  # <-- Change int to float
        top_p: Optional[float] = None,  # <-- Change int to float
        response_format: str = "text",
    ) -> Any:
        """
        Create an assistant record via AssistantService, bypassing the HTTP SDK.
        """

        # 1. Build a dictionary of arguments, excluding top_p and temperature for now
        kwargs = {
            "name": name,
            "model": model,
            "description": description,
            "instructions": instructions,
            "tools": tools or [],
            "tool_resources": tool_resources or {},
            "meta_data": meta_data or {},
            "web_access": web_access,
            "deep_research": deep_research,
            "engineer": engineer,
            "agent_mode": agent_mode,
            "decision_telemetry": decision_telemetry,
            "max_turns": max_turns,
            "response_format": response_format,
        }

        # 2. Only add them if they were actually provided, allowing Pydantic to use its defaults
        if temperature is not None:
            kwargs["temperature"] = temperature
        if top_p is not None:
            kwargs["top_p"] = top_p

        # 3. Spread kwargs into your Pydantic model
        req = self.val_interface.AssistantCreate(**kwargs)

        return await asyncio.to_thread(self.assistant_svc.create_assistant, req, user_id)

    async def retrieve_assistant(self, assistant_id: str) -> Any:
        """
        Fetch a single assistant directly from the DB via AssistantService,
        bypassing the HTTP SDK.

        Returns a validated AssistantRead object — identical shape to what the
        SDK call produced, so all downstream consumers (AssistantCache,
        OrchestratorCore config loaders) are drop-in compatible.

        Raises HTTPException(404) if the assistant does not exist or has been
        soft-deleted (propagated from AssistantService unchanged).
        """
        return await asyncio.to_thread(self.assistant_svc.retrieve_assistant, assistant_id)

    async def delete_assistant(
        self,
        assistant_id: str,
        user_id: str,
        permanent: bool = False,
    ) -> None:
        """
        Delete an assistant via AssistantService, bypassing the HTTP SDK.

        user_id must match the owner_id on the record — the ownership guard
        in AssistantService.delete_assistant enforces this.

        Used by AssistantManager for ephemeral cleanup and by
        _ephemeral_clean_up in OrchestratorCore.
        """
        return await asyncio.to_thread(
            self.assistant_svc.delete_assistant,
            assistant_id,
            user_id,
            permanent,
        )

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

        def _update():
            existing = self.action_svc.get_action(action_id)
            req = self.val_interface.ActionUpdate(
                status=status,
                result=existing.result,
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
        """
        import types

        req = types.SimpleNamespace(
            assistant_id=assistant_id,
            thread_id=thread_id,
            meta_data=meta_data or {},
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
        """
        import types

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
        """
        return await asyncio.to_thread(self.thread_svc.delete_thread, thread_id)

    async def get_formatted_messages(self, thread_id: str) -> list:
        """
        Fetch all messages for a thread formatted for LLM consumption,
        bypassing the HTTP SDK.
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

    async def update_run_fields(self, run_id: str, **fields) -> Any:
        """
        Update arbitrary lifecycle fields on a run record via RunService,
        bypassing the HTTP SDK.

        Accepts any keyword arguments that RunService.update_run_fields
        supports, e.g.:
            current_turn, started_at, completed_at, failed_at,
            last_error, incomplete_details

        Used exclusively by OrchestratorCore.process_conversation for
        turn-by-turn lifecycle stamping. Non-fatal callers should wrap
        this in try/except and log warnings on failure.
        """
        return await asyncio.to_thread(self.run_svc.update_run_fields, run_id, **fields)

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
        """Scrape a URL via the remote browserless container."""
        LOG.info(f"NativeExec ▸ read_url: {url} (force_refresh={force_refresh})")
        return await self.web_reader.read(url, force_refresh=force_refresh)

    async def scroll_url(self, url: str, page: int) -> str:
        """Return a specific page of a previously cached URL."""
        LOG.info(f"NativeExec ▸ scroll_url: {url} page={page}")
        return await self.web_reader.scroll(url, page)

    async def search_url(self, url: str, query: str) -> str:
        """Full-text search within the cached content of a URL."""
        LOG.info(f"NativeExec ▸ search_url: '{query}' in {url}")
        return await self.web_reader.search(url, query)

    async def serp_search(self, query: str) -> str:
        """Perform a live DuckDuckGo SERP search via the browser service."""
        LOG.info(f"NativeExec ▸ serp_search: '{query}'")
        return await self.web_reader.perform_serp_search(query)
