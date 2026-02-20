from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncGenerator, Dict, Optional

from projectdavid_common import ToolValidator
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

LOG = LoggingUtility()


class ScratchpadMixin:

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._scratch_pad_thread: Optional[str] = None

    async def _execute_scratchpad_logic(
        self,
        tool_name: str,
        operation_type: str,
        thread_id: Optional[str],
        run_id: str,
        assistant_id: str,
        arguments_dict: Dict[str, Any],
        tool_call_id: str,
        decision: Any,
    ) -> AsyncGenerator[str, None]:

        # Respect caller thread_id, fallback only if absent
        thread_id = thread_id or self._scratch_pad_thread

        _OP_LABELS = {
            "read": ("📖 Reading scratchpad...", "📖 Scratchpad read."),
            "update": ("✏️ Updating scratchpad...", "✏️ Scratchpad updated."),
            "append": ("📝 Appending to scratchpad...", "📝 Scratchpad entry written."),
        }

        label_start, label_done = _OP_LABELS.get(
            operation_type, ("Accessing memory...", "Memory synchronized.")
        )

        # --- START ACTIVITY EVENT ---
        yield json.dumps(
            {
                "type": "activity",
                "tool": tool_name,
                "activity": label_start,
                "state": "in_progress",
                "run_id": run_id,
                "operation": operation_type,
            }
        )

        # --- VALIDATION ---
        if operation_type != "read":
            required = {"content": str} if operation_type == "update" else {"note": str}

            validator = ToolValidator()
            validator.schema_registry = {tool_name: required}

            if err := validator.validate_args(tool_name, arguments_dict):
                yield json.dumps(
                    {
                        "type": "activity",
                        "tool": tool_name,
                        "activity": f"Validation error: {err}",
                        "state": "error",
                        "run_id": run_id,
                        "operation": operation_type,
                    }
                )

                await self.submit_tool_output(
                    thread_id=thread_id,
                    assistant_id=assistant_id,
                    tool_call_id=tool_call_id,
                    content=f"Error: {err}",
                    action=None,
                    is_error=True,
                )
                return

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
                    self.project_david_client.tools.scratchpad_read,
                    thread_id=thread_id,
                )
            elif operation_type == "update":
                res = await asyncio.to_thread(
                    self.project_david_client.tools.scratchpad_update,
                    thread_id=thread_id,
                    content=arguments_dict.get("content"),
                )
            else:
                res = await asyncio.to_thread(
                    self.project_david_client.tools.scratchpad_append,
                    thread_id=thread_id,
                    note=arguments_dict.get("note"),
                )

            payload = {
                "type": "activity",
                "tool": tool_name,
                "activity": label_done,
                "state": "completed",
                "run_id": run_id,
                "operation": operation_type,
                "data": None,
            }

            if operation_type == "append":
                payload["data"] = arguments_dict.get("note", "")
            elif operation_type == "update":
                payload["data"] = arguments_dict.get("content", "")
            elif operation_type == "read":
                payload["data"] = res

            yield json.dumps(payload)

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
            yield json.dumps(
                {
                    "type": "activity",
                    "tool": tool_name,
                    "activity": f"Scratchpad error: {str(e)}",
                    "state": "error",
                    "run_id": run_id,
                    "operation": operation_type,
                }
            )

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

    async def handle_read_scratchpad(self, *args, **kwargs):
        async for s in self._execute_scratchpad_logic(
            "read_scratchpad", "read", *args, **kwargs
        ):
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
