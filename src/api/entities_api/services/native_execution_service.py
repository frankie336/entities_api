import asyncio
from typing import Any, Dict, Optional

from projectdavid_common import ValidationInterface
from projectdavid_common.validation import StatusEnum

from src.api.entities_api.cache.scratchpad_cache import ScratchpadCache
from src.api.entities_api.db.database import SessionLocal
from src.api.entities_api.services.actions_service import ActionService
from src.api.entities_api.services.logging_service import LoggingUtility
from src.api.entities_api.services.message_service import MessageService
from src.api.entities_api.services.scratchpad_service import ScratchpadService
from src.api.entities_api.services.vectors_service import VectorStoreDBService

LOG = LoggingUtility()


class NativeExecutionService:
    """
    Helper service to manage native database executions, bypassing the HTTP SDK.
    Provides async-friendly wrappers around common Action and Message operations.
    """

    def __init__(self):
        self.action_svc = ActionService()
        self.message_svc = MessageService()
        self.val_interface = ValidationInterface()

        # Initialize native Scratchpad data-plane service
        self.scratchpad_svc = ScratchpadService(cache=ScratchpadCache())

    async def get_vector_store(self, vector_store_id: str) -> Any:
        """Fetches vector store metadata directly from the native DB."""

        def _fetch():
            with SessionLocal() as db:
                svc = VectorStoreDBService(db)
                return svc.get_vector_store_by_id(vector_store_id)

        return await asyncio.to_thread(_fetch)

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
