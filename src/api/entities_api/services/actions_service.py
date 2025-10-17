from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from projectdavid import Entity
from projectdavid_common import UtilsInterface, ValidationInterface
from projectdavid_common.utilities.logging_service import LoggingUtility
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# --- FIX: Step 1 ---
# Import the SessionLocal factory.
from src.api.entities_api.db.database import SessionLocal
from src.api.entities_api.models.models import Action, Run, Tool
from src.api.entities_api.utils.conversion_utils import datetime_to_iso

client = Entity()
validator = ValidationInterface()
logging_utility = LoggingUtility()


class ActionService:

    # --- FIX: Step 2 ---
    # The constructor no longer accepts or stores a database session.
    def __init__(self):
        logging_utility.info("ActionService initialized.")

    def update_action_stream_state(self, action_id: str, state: dict):
        # --- FIX: Step 3 ---
        # Each method now creates and manages its own session.
        with SessionLocal() as db:
            action = db.query(Action).get(action_id)
            if not action:
                raise HTTPException(status_code=404, detail="Action not found")
            action.meta = action.meta or {}
            action.meta["stream_state"] = {
                "buffer": state.get("buffer", []),
                "received_lines": state.get("received_lines", 0),
                "last_update": datetime.utcnow().isoformat(),
            }
            db.commit()

    def update_action_output(
        self, action_id: str, new_content: str, is_partial: bool = True
    ):
        with SessionLocal() as db:
            action = db.query(Action).get(action_id)
            if not action:
                raise HTTPException(status_code=404, detail="Action not found")
            if not action.result or isinstance(action.result, str):
                action.result = {
                    "full_output": "",
                    "partials": [],
                    "status": "in_progress",
                }
            if is_partial:
                action.result["partials"].append(
                    {"content": new_content, "timestamp": datetime.utcnow().isoformat()}
                )
            else:
                action.result["full_output"] = new_content
                action.result["status"] = "completed"
                action.status = validator.ActionStatus.completed
                action.processed_at = datetime.utcnow()
            db.commit()

    def create_action(
        self, action_data: validator.ActionCreate
    ) -> validator.ActionRead:
        logging_utility.info(
            "Creating action for tool_name: %s, run_id: %s",
            action_data.tool_name,
            action_data.run_id,
        )
        with SessionLocal() as db:
            try:
                logging_utility.debug(
                    "Received ActionCreate payload: %s", action_data.dict()
                )
                tool = db.query(Tool).filter(Tool.name == action_data.tool_name).first()
                if not tool:
                    logging_utility.warning(
                        "Tool with name %s not found.", action_data.tool_name
                    )
                    raise HTTPException(
                        status_code=404,
                        detail=f"Tool with name {action_data.tool_name} not found",
                    )
                logging_utility.debug(
                    "Fetched tool: %s", {"id": tool.id, "name": tool.name}
                )
                new_action_id = UtilsInterface.IdentifierService.generate_action_id()
                logging_utility.debug("Generated new action ID: %s", new_action_id)
                status = action_data.status
                logging_utility.debug("Using status: %s", status)
                new_action = Action(
                    id=new_action_id,
                    tool_id=tool.id,
                    run_id=action_data.run_id,
                    triggered_at=datetime.now(),
                    expires_at=action_data.expires_at,
                    function_args=action_data.function_args,
                    status=status,
                )
                logging_utility.debug(
                    "New Action object details: %s", new_action.__dict__
                )
                db.add(new_action)
                db.commit()
                db.refresh(new_action)
                logging_utility.info("New action committed with ID: %s", new_action.id)
                return validator.ActionRead(
                    id=new_action.id, status=new_action.status, result=new_action.result
                )
            except IntegrityError as e:
                db.rollback()
                logging_utility.error(
                    "IntegrityError during action creation: %s", str(e)
                )
                logging_utility.exception("IntegrityError traceback:")
                raise HTTPException(
                    status_code=400, detail="Invalid action data or duplicate entry"
                )
            except Exception as e:
                db.rollback()
                logging_utility.error(
                    "Unexpected error during action creation: %s", str(e)
                )
                logging_utility.exception("Full exception traceback:")
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
                    logging_utility.error(
                        "Action not found in DB. Queried ID: %s", action_id
                    )
                    raise HTTPException(
                        status_code=404, detail=f"Action {action_id} not found"
                    )
                # Assuming client.tool_service is also refactored or safe to call
                tool = client.tool_service.get_tool_by_id(tool_id=action.tool_id)
                return validator.ActionRead(
                    id=action.id,
                    run_id=action.run_id,
                    tool_id=action.tool_id,
                    tool_name=tool.name,
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
        """Update the status of an action and store the result."""
        with SessionLocal() as db:
            try:
                action = db.query(Action).filter(Action.id == action_id).first()
                if not action:
                    raise HTTPException(
                        status_code=404, detail=f"Action with ID {action_id} not found"
                    )
                if action_update.status not in validator.ActionStatus.__members__:
                    raise HTTPException(status_code=400, detail="Invalid status value")
                action.status = action_update.status
                action.result = action_update.result
                if action_update.status == validator.ActionStatus.completed:
                    action.is_processed = True
                    action.processed_at = datetime.now()
                db.commit()
                db.refresh(action)
                return validator.ActionRead(
                    id=action.id,
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
        """Retrieve actions by run_id and status with proper datetime conversion."""
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
        Retrieve all pending actions with their function arguments, tool names, and run details.
        Optionally filter by run_id.
        """
        with SessionLocal() as db:
            query = (
                db.query(
                    Action.id.label("action_id"),
                    Action.status.label("action_status"),
                    Action.function_args.label("function_arguments"),
                    Tool.name.label("tool_name"),
                    Run.id.label("run_id"),
                    Run.status.label("run_status"),
                )
                .join(Tool, Action.tool_id == Tool.id)
                .join(Run, Action.run_id == Run.id)
                .filter(Action.status == "pending")
            )
            if run_id:
                query = query.filter(Action.run_id == run_id)
            pending_actions = query.all()
            return [row._asdict() for row in pending_actions]

    def delete_action(self, action_id: str) -> None:
        """Delete an action by its ID."""
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
