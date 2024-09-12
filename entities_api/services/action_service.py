from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from models.models import Action, Tool, Run
from typing import List, Optional, Dict, Any
from entities_api.services.logging_service import LoggingUtility
from entities_api.schemas import ActionCreate, ActionRead, ActionUpdate, ActionList
from datetime import datetime
from entities_api.services.identifier_service import IdentifierService

logging_utility = LoggingUtility()


class ActionService:
    def __init__(self, db: Session):
        self.db = db
        logging_utility.info("ActionService initialized with database session.")

    def create_action(self, action_data: ActionCreate) -> ActionRead:
        """Create a new action for a tool call, by searching tool by name."""
        logging_utility.info("Creating action for tool_name: %s, run_id: %s", action_data.tool_name, action_data.run_id)
        try:
            # Validate that the tool_name exists in the tools table
            tool = self.db.query(Tool).filter(Tool.name == action_data.tool_name).first()
            if not tool:
                logging_utility.warning("Tool with name %s not found.", action_data.tool_name)
                raise HTTPException(status_code=404, detail=f"Tool with name {action_data.tool_name} not found")

            action_id = IdentifierService.generate_action_id()  # Generate action ID using IdentifierService
            logging_utility.debug("Generated action ID: %s", action_id)

            new_action = Action(
                id=action_id,  # Use generated action ID
                tool_id=tool.id,  # Use tool's ID from the tool lookup
                run_id=action_data.run_id,
                triggered_at=datetime.now(),
                expires_at=action_data.expires_at,
                function_args=action_data.function_args,
                status="pending"
            )
            logging_utility.debug("New action to be added to the database: %s", new_action)

            self.db.add(new_action)
            self.db.commit()
            self.db.refresh(new_action)

            logging_utility.info("Action created successfully with ID: %s", new_action.id)
            return ActionRead(
                id=new_action.id,
                status=new_action.status,
                result=new_action.result
            )

        except IntegrityError as e:
            self.db.rollback()
            logging_utility.error("IntegrityError during action creation: %s", str(e))
            raise HTTPException(status_code=400, detail="Invalid action data or duplicate entry")
        except Exception as e:
            self.db.rollback()
            logging_utility.error("Unexpected error during action creation: %s", str(e))
            raise HTTPException(status_code=500, detail="An error occurred while creating the action")

    def get_action(self, action_id: str) -> ActionRead:
        """Retrieve an action by its ID."""
        logging_utility.info("Retrieving action with ID: %s", action_id)
        try:
            action = self.db.query(Action).filter(Action.id == action_id).first()

            if not action:
                logging_utility.warning("Action with ID %s not found", action_id)
                raise HTTPException(status_code=404, detail=f"Action with id {action_id} not found")

            logging_utility.info("Action retrieved successfully: %s", action)

            # Properly convert the SQLAlchemy action object to a Pydantic model
            # Ensuring that all required fields are populated and no Pydantic internals are exposed
            return ActionRead(
                id=action.id,
                run_id=action.run_id,
                triggered_at=action.triggered_at,
                expires_at=action.expires_at,
                is_processed=action.is_processed,
                processed_at=action.processed_at,
                status=action.status,
                function_args=action.function_args,
                result=action.result
            )

        except HTTPException as e:
            logging_utility.error("HTTPException: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("Unexpected error retrieving action: %s", str(e))
            raise HTTPException(status_code=500, detail="An error occurred while retrieving the action")

    def update_action_status(self, action_id: str, action_update: ActionUpdate) -> ActionRead:
        """Update the status of an action and store the result."""
        try:
            action = self.db.query(Action).filter(Action.id == action_id).first()

            if not action:
                raise HTTPException(status_code=404, detail=f"Action with ID {action_id} not found")

            # Update action status and result
            action.status = action_update.status
            if action_update.result:
                action.result = action_update.result
            if action_update.status == "completed":
                action.is_processed = True
                action.processed_at = datetime.now()

            self.db.commit()
            self.db.refresh(action)

            # Convert SQLAlchemy object to dictionary and pass it to Pydantic for validation
            action_dict = {
                "id": action.id,
                "status": action.status,
                "result": action.result
            }

            return ActionRead(**action_dict)  # Pydantic validation
        except Exception as e:
            self.db.rollback()
            logging_utility.error(f"Error updating action status: {str(e)}")
            raise HTTPException(status_code=500, detail="An error occurred while updating the action status")

    def get_actions_by_status(self, run_id: str, status: Optional[str] = "pending") -> List[ActionRead]:
        """Retrieve actions by run_id and status."""
        logging_utility.info(f"Retrieving actions for run_id: {run_id} with status: {status}")
        try:
            actions = self.db.query(Action).filter(Action.run_id == run_id, Action.status == status).all()

            if not actions:
                logging_utility.info(f"No actions found for run_id {run_id} with status {status}.")
                return []

            logging_utility.info(f"Retrieved {len(actions)} actions for run_id {run_id} with status {status}.")
            return [ActionRead(
                id=action.id,
                run_id=action.run_id,
                triggered_at=action.triggered_at,
                expires_at=action.expires_at,
                is_processed=action.is_processed,
                processed_at=action.processed_at,
                status=action.status,
                function_args=action.function_args,
                result=action.result
            ) for action in actions]

        except Exception as e:
            logging_utility.error(f"Error retrieving actions for run {run_id} with status {status}: {str(e)}")
            raise HTTPException(status_code=500, detail="An error occurred while retrieving the actions.")

    def delete_action(self, action_id: str) -> None:
        """Delete an action by its ID."""
        logging_utility.info("Deleting action with ID: %s", action_id)
        try:
            action = self.db.query(Action).filter(Action.id == action_id).first()

            if not action:
                logging_utility.warning("Action with ID %s not found", action_id)
                raise HTTPException(status_code=404, detail=f"Action with id {action_id} not found")

            self.db.delete(action)
            self.db.commit()

            logging_utility.info("Action with ID %s deleted successfully", action_id)
        except Exception as e:
            self.db.rollback()
            logging_utility.error("Error deleting action: %s", str(e))
            raise HTTPException(status_code=500, detail="An error occurred while deleting the action")
