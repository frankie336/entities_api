from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator, Dict, List, Optional

from projectdavid.events import StatusEvent
from projectdavid_common import ToolValidator
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from src.api.entities_api.utils.level3_utils import create_status_payload

LOG = LoggingUtility()


class ScratchpadMixin:
    """
    Handles the 'Working Memory' tools.
    Allows the agent to Read, Overwrite, and Append to a persistent text buffer.
    """

    async def _execute_scratchpad_logic(
        self,
        tool_name: str,
        operation_type: str,  # 'read', 'update', 'append'
        thread_id: str,
        run_id: str,
        assistant_id: str,
        arguments_dict: Dict[str, Any],
        tool_call_id: Optional[str],
        decision: Optional[Dict],
    ) -> AsyncGenerator[StatusEvent, None]:

        # --- [1] STATUS: STARTING ---
        yield create_status_payload(run_id, tool_name, "Accessing memory...")

        # --- [2] VALIDATION ---
        # (read_scratchpad has no args, others do)
        if operation_type != "read":
            required = ["content"] if operation_type == "update" else ["note"]
            validator = ToolValidator()
            validator.schema_registry = {tool_name: required}
            if err := validator.validate_args(tool_name, arguments_dict):
                yield create_status_payload(
                    run_id, tool_name, "Validation failed", state="error"
                )
                await self.submit_tool_output(
                    thread_id, assistant_id, tool_call_id, f"Error: {err}", None, True
                )
                return

        # --- [3] CREATE ACTION RECORD ---
        try:
            action = await asyncio.to_thread(
                self.project_david_client.actions.create_action,
                tool_name=tool_name,
                run_id=run_id,
                tool_call_id=tool_call_id,
                function_args=arguments_dict,
                decision=decision,
            )
        except Exception as e:
            LOG.error(f"Scratchpad Action Creation Failed: {e}")
            yield create_status_payload(
                run_id, tool_name, "System error", state="error"
            )
            return

        # --- [4] EXECUTION ---
        try:
            result_content = ""

            if operation_type == "read":
                yield create_status_payload(run_id, tool_name, "Reading notes...")
                result_content = await asyncio.to_thread(
                    self.project_david_client.tools.scratchpad_read, thread_id=thread_id
                )

            elif operation_type == "update":
                yield create_status_payload(run_id, tool_name, "Updating plan...")
                content_val = arguments_dict["content"]
                result_content = await asyncio.to_thread(
                    self.project_david_client.tools.scratchpad_update,
                    thread_id=thread_id,
                    content=content_val,
                )

            elif operation_type == "append":
                yield create_status_payload(run_id, tool_name, "Saving note...")
                note_val = arguments_dict["note"]
                result_content = await asyncio.to_thread(
                    self.project_david_client.tools.scratchpad_append,
                    thread_id=thread_id,
                    note=note_val,
                )

            # --- [5] SUCCESS ---
            yield create_status_payload(
                run_id, tool_name, "Memory updated.", state="success"
            )

            await asyncio.to_thread(
                self.project_david_client.actions.update_action,
                action_id=action.id,
                status=StatusEnum.completed.value,
            )

            await self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                content=result_content,
                action=action,
            )

        except Exception as e:
            # --- [6] FAILURE ---
            LOG.error(f"Scratchpad Execution Error: {e}")
            yield create_status_payload(
                run_id, tool_name, f"Error: {str(e)}", state="error"
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
                content=f"Error accessing scratchpad: {str(e)}",
                action=action,
                is_error=True,
            )

    # ------------------------------------------------------------------
    # HANDLERS
    # ------------------------------------------------------------------

    async def handle_read_scratchpad(
        self,
        thread_id: str,
        run_id: str,
        assistant_id: str,
        arguments_dict: Dict,
        tool_call_id: str,
        decision: Dict,
    ):
        async for status in self._execute_scratchpad_logic(
            "read_scratchpad",
            "read",
            thread_id,
            run_id,
            assistant_id,
            arguments_dict,
            tool_call_id,
            decision,
        ):
            yield status

    async def handle_update_scratchpad(
        self,
        thread_id: str,
        run_id: str,
        assistant_id: str,
        arguments_dict: Dict,
        tool_call_id: str,
        decision: Dict,
    ):
        async for status in self._execute_scratchpad_logic(
            "update_scratchpad",
            "update",
            thread_id,
            run_id,
            assistant_id,
            arguments_dict,
            tool_call_id,
            decision,
        ):
            yield status

    async def handle_append_scratchpad(
        self,
        thread_id: str,
        run_id: str,
        assistant_id: str,
        arguments_dict: Dict,
        tool_call_id: str,
        decision: Dict,
    ):
        async for status in self._execute_scratchpad_logic(
            "append_scratchpad",
            "append",
            thread_id,
            run_id,
            assistant_id,
            arguments_dict,
            tool_call_id,
            decision,
        ):
            yield status
