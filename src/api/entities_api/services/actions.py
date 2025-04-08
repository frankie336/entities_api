from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from projectdavid import Entity
from projectdavid_common import UtilsInterface, ValidationInterface
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from entities_api.models.models import Action, Tool
from entities_api.services.logging_service import LoggingUtility
from entities_api.utils.conversion_utils import datetime_to_iso

client = Entity()

validator = ValidationInterface()


from entities_api.models.models import Run  # Ensure Run is imported

logging_utility = LoggingUtility()


class ActionService:
    def __init__(self, db: Session):
        self.db = db
        logging_utility.info("ActionService initialized with database session.")

    # In ActionService class
    def update_action_stream_state(self, action_id: str, state: dict):
        action = self.db.query(Action).get(action_id)
        if not action:
            raise HTTPException(status_code=404, detail="Action not found")

        action.meta = action.meta or {}
        action.meta["stream_state"] = {
            "buffer": state.get("buffer", []),
            "received_lines": state.get("received_lines", 0),
            "last_update": datetime.utcnow().isoformat(),
        }
        self.db.commit()

    def update_action_output(
        self, action_id: str, new_content: str, is_partial: bool = True
    ):
        action = self.db.query(Action).get(action_id)
        if not action:
            raise HTTPException(status_code=404, detail="Action not found")

        # Initialize structured result
        if not action.result or isinstance(action.result, str):
            action.result = {"full_output": "", "partials": [], "status": "in_progress"}

        if is_partial:
            action.result["partials"].append(
                {"content": new_content, "timestamp": datetime.utcnow().isoformat()}
            )
        else:
            action.result["full_output"] = new_content
            action.result["status"] = "completed"
            action.status = validator.ActionStatus.completed
            action.processed_at = datetime.utcnow()

        self.db.commit()

    def create_action(
        self, action_data: validator.ActionCreate
    ) -> validator.ActionRead:
        logging_utility.info(
            "Creating action for tool_name: %s, run_id: %s",
            action_data.tool_name,
            action_data.run_id,
        )
        try:
            # Log the received ActionCreate data
            logging_utility.debug(
                "Received ActionCreate payload: %s", action_data.dict()
            )

            # Validate that the tool_name exists in the tools table
            tool = (
                self.db.query(Tool).filter(Tool.name == action_data.tool_name).first()
            )
            if not tool:
                logging_utility.warning(
                    "Tool with name %s not found.", action_data.tool_name
                )
                raise HTTPException(
                    status_code=404,
                    detail=f"Tool with name {action_data.tool_name} not found",
                )

            # Log the fetched tool details
            logging_utility.debug(
                "Fetched tool: %s", {"id": tool.id, "name": tool.name}
            )

            # Generate a new action id (or decide if you want to use action_data.id)
            new_action_id = UtilsInterface.IdentifierService.generate_action_id()
            logging_utility.debug("Generated new action ID: %s", new_action_id)

            # Use the provided status (should be a string, as expected)
            status = action_data.status
            logging_utility.debug("Using status: %s", status)

            # Build the Action model object
            new_action = Action(
                id=new_action_id,
                tool_id=tool.id,
                run_id=action_data.run_id,
                triggered_at=datetime.now(),
                expires_at=action_data.expires_at,
                function_args=action_data.function_args,
                status=status,
            )
            logging_utility.debug("New Action object details: %s", new_action.__dict__)

            self.db.add(new_action)
            self.db.commit()
            self.db.refresh(new_action)
            logging_utility.info("New action committed with ID: %s", new_action.id)

            return validator.ActionRead(
                id=new_action.id, status=new_action.status, result=new_action.result
            )
        except IntegrityError as e:
            self.db.rollback()
            logging_utility.error("IntegrityError during action creation: %s", str(e))
            logging_utility.exception("IntegrityError traceback:")
            raise HTTPException(
                status_code=400, detail="Invalid action data or duplicate entry"
            )
        except Exception as e:
            self.db.rollback()
            logging_utility.error("Unexpected error during action creation: %s", str(e))
            logging_utility.exception("Full exception traceback:")
            raise HTTPException(
                status_code=500, detail="An error occurred while creating the action"
            )

    def get_action(self, action_id: str) -> validator.ActionRead:
        """Retrieve an action by its ID with proper datetime conversion."""
        logging_utility.info("Retrieving action with ID: %s", action_id)
        try:
            self.db.commit()  # Refresh session state
            action = self.db.query(Action).filter(Action.id == action_id).first()

            if not action:
                logging_utility.error(
                    "Action not found in DB. Queried ID: %s", action_id
                )
                raise HTTPException(
                    status_code=404, detail=f"Action {action_id} not found"
                )

            # we indirectly fetch the tool name by id which is already available on another end point
            tool = client.tool_service.get_tool_by_id(tool_id=action.tool_id)

            return validator.ActionRead(
                id=action.id,
                run_id=action.run_id,
                tool_id=action.tool_id,
                tool_name=tool.name,
                triggered_at=datetime_to_iso(
                    action.triggered_at
                ),  # Use conversion utility
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
        try:
            action = self.db.query(Action).filter(Action.id == action_id).first()
            if not action:
                raise HTTPException(
                    status_code=404, detail=f"Action with ID {action_id} not found"
                )

            # Validate status value by checking the ActionStatus enum
            if action_update.status not in validator.ActionStatus.__members__:
                raise HTTPException(status_code=400, detail="Invalid status value")

            # Update fields
            action.status = action_update.status
            action.result = action_update.result
            if (
                action_update.status == validator.ActionStatus.completed
            ):  # Use the enum value here
                action.is_processed = True
                action.processed_at = datetime.now()

            self.db.commit()
            self.db.refresh(action)

            # Return the updated ActionRead object
            return validator.ActionRead(
                id=action.id,
                status=action.status,
                result=action.result,
                processed_at=datetime_to_iso(
                    action.processed_at
                ),  # Add converted field
            )

        except Exception as e:
            self.db.rollback()
            logging_utility.error(f"Error updating action status: {str(e)}")
            raise HTTPException(status_code=500, detail="Error updating action status")

    def get_actions_by_status(
        self, run_id: str, status: Optional[str] = "pending"
    ) -> List[validator.ActionRead]:
        """Retrieve actions by run_id and status with proper datetime conversion."""
        logging_utility.info(
            f"Retrieving actions for run_id: {run_id} with status: {status}"
        )
        try:
            actions = (
                self.db.query(Action)
                .filter(Action.run_id == run_id, Action.status == status)
                .all()
            )
            return [
                validator.ActionRead(
                    id=action.id,
                    run_id=action.run_id,
                    triggered_at=datetime_to_iso(action.triggered_at),  # Convert here
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
        query = (
            self.db.query(
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

        return [dict(row) for row in pending_actions]

    def delete_action(self, action_id: str) -> None:
        """Delete an action by its ID."""
        logging_utility.info("Deleting action with ID: %s", action_id)
        try:
            action = self.db.query(Action).filter(Action.id == action_id).first()

            if not action:
                logging_utility.warning("Action with ID %s not found", action_id)
                raise HTTPException(
                    status_code=404, detail=f"Action with id {action_id} not found"
                )

            self.db.delete(action)
            self.db.commit()

            logging_utility.info("Action with ID %s deleted successfully", action_id)
        except Exception as e:
            self.db.rollback()
            logging_utility.error("Error deleting action: %s", str(e))
            raise HTTPException(
                status_code=500, detail="An error occurred while deleting the action"
            )
