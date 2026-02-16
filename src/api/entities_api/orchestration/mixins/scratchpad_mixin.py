from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncGenerator, Dict, Optional

from projectdavid_common import ToolValidator
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

LOG = LoggingUtility()


# src/api/entities_api/orchestration/mixins/scratchpad_mixin.py
class ScratchpadMixin:
    async def _execute_scratchpad_logic(
        self,
        tool_name,
        operation_type,
        thread_id,
        run_id,
        assistant_id,
        arguments_dict,
        tool_call_id,
        decision,
    ) -> AsyncGenerator[Dict, None]:

        yield {
            "type": "status",
            "status": f"Accessing memory ({operation_type})...",
            "state": "in_progress",
            "run_id": run_id,
        }

        if operation_type != "read":
            from projectdavid_common import ToolValidator

            required = ["content"] if operation_type == "update" else ["note"]
            validator = ToolValidator()
            validator.schema_registry = {tool_name: required}
            if err := validator.validate_args(tool_name, arguments_dict):

                await self.submit_tool_output(
                    thread_id=thread_id,
                    assistant_id=assistant_id,
                    tool_call_id=tool_call_id,
                    content=f"Error: {err}",
                    action=None,
                    is_error=True,
                )

        action = await asyncio.to_thread(
            self.project_david_client.actions.create_action,
            tool_name=tool_name,
            run_id=run_id,
            tool_call_id=tool_call_id,
            function_args=arguments_dict,
            decision=decision,
        )

        try:
            if operation_type == "read":
                res = await asyncio.to_thread(
                    self.project_david_client.tools.scratchpad_read, thread_id=thread_id
                )
            elif operation_type == "update":
                res = await asyncio.to_thread(
                    self.project_david_client.tools.scratchpad_update,
                    thread_id=thread_id,
                    content=arguments_dict["content"],
                )
            else:
                res = await asyncio.to_thread(
                    self.project_david_client.tools.scratchpad_append,
                    thread_id=thread_id,
                    note=arguments_dict["note"],
                )

            yield {
                "type": "status",
                "status": "Memory synchronized.",
                "state": "success",
                "run_id": run_id,
            }

            await asyncio.to_thread(
                self.project_david_client.actions.update_action,
                action_id=action.id,
                status=StatusEnum.completed.value,
            )
            await self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                content=res,
                action=action,
            )
        except Exception as e:
            yield {
                "type": "status",
                "status": "Memory error.",
                "state": "error",
                "run_id": run_id,
            }
            await asyncio.to_thread(
                self.project_david_client.actions.update_action,
                action_id=action.id,
                status=StatusEnum.failed.value,
            )
            await self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                content=f"Error: {e}",
                action=action,
                is_error=True,
            )

    # Handlers simply yield from logic...
    async def handle_read_scratchpad(self, *args, **kwargs):
        async for s in self._execute_scratchpad_logic("read_scratchpad", "read", *args, **kwargs):
            yield s

    async def handle_update_scratchpad(self, *args, **kwargs):
        async for s in self._execute_scratchpad_logic(
            "update_scratchpad", "update", *args, **kwargs
        ):
            yield s

    async def handle_append_scratchpad(self, *args, **kwargs):
        async for s in self._execute_scratchpad_logic(
            "append_scratchpad", "append", *args, **kwargs
        ):
            yield s
