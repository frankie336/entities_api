# src/api/entities_api/services/actions_service.py
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from projectdavid_common import UtilsInterface, ValidationInterface
from projectdavid_common.utilities.logging_service import LoggingUtility
from sqlalchemy.exc import IntegrityError

from src.api.entities_api.db.database import SessionLocal
# FIX: Removed Tool from imports, kept Action and Run
from src.api.entities_api.models.models import Action, Run
from src.api.entities_api.utils.conversion_utils import datetime_to_iso

validator = ValidationInterface()
logging_utility = LoggingUtility()


class ActionService:
    def __init__(self):
        logging_utility.info("ActionService initialized.")

    def update_action_stream_state(self, action_id: str, state: dict):
        with SessionLocal() as db:
            action = db.query(Action).get(action_id)
            if not action:
                raise HTTPException(status_code=404, detail="Action not found")

            # Initialize meta if None
            if action.meta_data is None:
                action.meta_data = {}

            # Update stream state inside meta_data
            # Note: Ensure your Action model has 'meta_data' (JSON),
            # previous schema showed it might be 'meta' or 'meta_data'.
            # Based on standard patterns, usually 'meta_data'.
            current_meta = dict(action.meta_data) if action.meta_data else {}
            current_meta["stream_state"] = {
                "buffer": state.get("buffer", []),
                "received_lines": state.get("received_lines", 0),
                "last_update": datetime.utcnow().isoformat(),
            }
            action.meta_data = current_meta

            db.commit()

    def update_action_output(
        self, action_id: str, new_content: str, is_partial: bool = True
    ):
        with SessionLocal() as db:
            action = db.query(Action).get(action_id)
            if not action:
                raise HTTPException(status_code=404, detail="Action not found")

            # Initialize result structure
            if not action.result or isinstance(action.result, str):
                action.result = {
                    "full_output": "",
                    "partials": [],
                    "status": "in_progress",
                }

            # Mutate the dictionary (SQLAlchemy MutableDict tracking or reassignment)
            current_result = dict(action.result)

            if is_partial:
                current_result["partials"].append(
                    {"content": new_content, "timestamp": datetime.utcnow().isoformat()}
                )
            else:
                current_result["full_output"] = new_content
                current_result["status"] = "completed"
                action.status = validator.ActionStatus.completed
                action.processed_at = datetime.utcnow()

            action.result = current_result
            db.commit()

    def create_action(
        self, action_data: validator.ActionCreate
    ) -> validator.ActionRead:
        logging_utility.info(
            "Creating action for tool_call_id: %s, run_id: %s",
            action_data.tool_call_id,
            action_data.run_id,
        )
        with SessionLocal() as db:
            try:
                # FIX: Removed tool lookup (db.query(Tool)...)
                # We no longer validate against a 'tools' table.
                # The Orchestrator is responsible for sending valid tool calls.

                new_action_id = UtilsInterface.IdentifierService.generate_action_id()

                new_action = Action(
                    id=new_action_id,
                    # FIX: Removed tool_id assignment
                    run_id=action_data.run_id,
                    triggered_at=datetime.now(),
                    expires_at=action_data.expires_at,
                    function_args=action_data.function_args,
                    status=action_data.status,
                    # --- NEW FIELDS ---
                    tool_call_id=action_data.tool_call_id,
                    turn_index=action_data.turn_index,
                )

                db.add(new_action)
                db.commit()
                db.refresh(new_action)

                logging_utility.info(
                    "New action committed with ID: %s (call_id: %s)",
                    new_action.id,
                    new_action.tool_call_id,
                )

                return validator.ActionRead(
                    id=new_action.id,
                    tool_call_id=new_action.tool_call_id,
                    status=new_action.status,
                    result=new_action.result,
                    # We accept that tool_name might be null in the Read response
                    # unless we pass what came in, but ActionRead usually requires it from DB.
                    # Mapping tool_name to tool_call_id or "dynamic" as fallback.
                    tool_name=action_data.tool_name or "dynamic_tool",
                )
            except IntegrityError as e:
                db.rollback()
                logging_utility.error(
                    "IntegrityError during action creation: %s", str(e)
                )
                raise HTTPException(
                    status_code=400, detail="Invalid action data or duplicate entry"
                )
            except Exception as e:
                db.rollback()
                logging_utility.error(
                    "Unexpected error during action creation: %s", str(e)
                )
                raise HTTPException(
                    status_code=500,
                    detail="An error occurred while creating the action",
                )

    def get_action(self, action_id: str) -> validator.ActionRead:
        """Retrieve an action by its ID with proper datetime conversion."""
        logging_utility.info("Retrieving action with ID: %s", action_id)
        with SessionLocal() as db:
            try:
                action = db.query(Action).filter(Action.id == action_id).first()
                if not action:
                    raise HTTPException(
                        status_code=404, detail=f"Action {action_id} not found"
                    )

                # FIX: Removed client.tool_service.get_tool_by_id(...)
                # Since we don't store the name, we assume the caller has context
                # or we just return the tool_call_id as the name reference.

                return validator.ActionRead(
                    id=action.id,
                    run_id=action.run_id,
                    # tool_id removed from response
                    tool_name=action.tool_call_id,  # Fallback, as name is not in DB
                    # --- NEW FIELDS ---
                    tool_call_id=action.tool_call_id,
                    turn_index=action.turn_index,
                    # ------------------
                    triggered_at=datetime_to_iso(action.triggered_at),
                    expires_at=datetime_to_iso(action.expires_at),
                    is_processed=action.is_processed,
                    processed_at=datetime_to_iso(action.processed_at),
                    status=action.status,
                    function_args=action.function_args,
                    result=action.result,
                )
            except Exception as e:
                logging_utility.error("Database error: %s", str(e))
                raise HTTPException(status_code=500, detail="Internal server error")

    def update_action_status(
        self, action_id: str, action_update: validator.ActionUpdate
    ) -> validator.ActionRead:
        with SessionLocal() as db:
            try:
                action = db.query(Action).filter(Action.id == action_id).first()
                if not action:
                    raise HTTPException(
                        status_code=404, detail=f"Action with ID {action_id} not found"
                    )

                # Validation of status enum
                # Ensure Validator uses strings or Enums correctly matching DB
                if isinstance(action_update.status, str):
                    # If it's a raw string, we trust it matches the enum or let DB fail
                    action.status = action_update.status
                else:
                    action.status = action_update.status

                action.result = action_update.result

                # Check against enum or string value 'completed'
                if str(action_update.status) == "completed":
                    action.is_processed = True
                    action.processed_at = datetime.now()

                db.commit()
                db.refresh(action)

                return validator.ActionRead(
                    id=action.id,
                    tool_call_id=action.tool_call_id,
                    tool_name=action.tool_call_id,  # Fallback
                    status=action.status,
                    result=action.result,
                    processed_at=datetime_to_iso(action.processed_at),
                )
            except Exception as e:
                db.rollback()
                logging_utility.error(f"Error updating action status: {str(e)}")
                raise HTTPException(
                    status_code=500, detail="Error updating action status"
                )

    def get_actions_by_status(
        self, run_id: str, status: Optional[str] = "pending"
    ) -> List[validator.ActionRead]:
        logging_utility.info(
            f"Retrieving actions for run_id: {run_id} with status: {status}"
        )
        with SessionLocal() as db:
            try:
                actions = (
                    db.query(Action)
                    .filter(Action.run_id == run_id, Action.status == status)
                    .all()
                )
                return [
                    validator.ActionRead(
                        id=action.id,
                        run_id=action.run_id,
                        tool_call_id=action.tool_call_id,
                        tool_name=action.tool_call_id,  # Fallback
                        triggered_at=datetime_to_iso(action.triggered_at),
                        expires_at=datetime_to_iso(action.expires_at),
                        is_processed=action.is_processed,
                        processed_at=datetime_to_iso(action.processed_at),
                        status=action.status,
                        function_args=action.function_args,
                        result=action.result,
                    )
                    for action in actions
                ]
            except Exception as e:
                logging_utility.error(f"Error retrieving actions: {str(e)}")
                raise HTTPException(status_code=500, detail="Error retrieving actions")

    def get_pending_actions(self, run_id=None) -> List[Dict[str, Any]]:
        """
        Retrieves pending actions.
        FIX: Removed the JOIN on the 'tools' table.
        """
        with SessionLocal() as db:
            query = (
                db.query(
                    Action.id.label("action_id"),
                    Action.tool_call_id.label("tool_call_id"),
                    Action.status.label("action_status"),
                    Action.function_args.label("function_arguments"),
                    # FIX: We cannot fetch Tool.name anymore.
                    # The consumer must rely on tool_call_id or function_args.
                    Action.tool_call_id.label(
                        "tool_name"
                    ),  # Using call_id as proxy for name if needed
                    Run.id.label("run_id"),
                    Run.status.label("run_status"),
                )
                # FIX: Removed .join(Tool, ...)
                .join(Run, Action.run_id == Run.id).filter(Action.status == "pending")
            )

            if run_id:
                query = query.filter(Action.run_id == run_id)

            pending_actions = query.all()
            return [row._asdict() for row in pending_actions]

    def delete_action(self, action_id: str) -> None:
        logging_utility.info("Deleting action with ID: %s", action_id)
        with SessionLocal() as db:
            try:
                action = db.query(Action).filter(Action.id == action_id).first()
                if not action:
                    logging_utility.warning("Action with ID %s not found", action_id)
                    raise HTTPException(
                        status_code=404, detail=f"Action with id {action_id} not found"
                    )
                db.delete(action)
                db.commit()
                logging_utility.info(
                    "Action with ID %s deleted successfully", action_id
                )
            except Exception as e:
                db.rollback()
                logging_utility.error("Error deleting action: %s", str(e))
                raise HTTPException(
                    status_code=500,
                    detail="An error occurred while deleting the action",
                )
