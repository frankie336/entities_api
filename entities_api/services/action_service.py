from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from models.models import Action, Tool, Run
from typing import List, Optional
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
            return ActionRead.model_validate(action)
        except HTTPException as e:
            logging_utility.error("HTTPException: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("Unexpected error retrieving action: %s", str(e))
            raise HTTPException(status_code=500, detail="An error occurred while retrieving the action")

    def update_action_status(self, action_id: str, action_update: ActionUpdate) -> ActionRead:
        """Update the status of an action (e.g., processing, completed, failed) and store the result."""
        logging_utility.info("Updating action with ID: %s to status: %s", action_id, action_update.status)
        try:
            action = self.db.query(Action).filter(Action.id == action_id).first()

            if not action:
                logging_utility.warning("Action with ID %s not found", action_id)
                raise HTTPException(status_code=404, detail=f"Action with id {action_id} not found")

            action.status = action_update.status
            if action_update.result:
                action.result = action_update.result
            if action_update.status == "completed":
                action.is_processed = True
                action.processed_at = datetime.now()

            self.db.commit()
            self.db.refresh(action)

            logging_utility.info("Action with ID %s updated successfully to status: %s", action_id, action_update.status)
            return ActionRead.model_validate(action)
        except Exception as e:
            self.db.rollback()
            logging_utility.error("Error updating action status: %s", str(e))
            raise HTTPException(status_code=500, detail="An error occurred while updating the action status")

    def list_actions_for_run(self, run_id: str) -> ActionList:
        """List all actions associated with a specific run."""
        logging_utility.info("Listing actions for run_id: %s", run_id)
        try:
            actions = self.db.query(Action).filter(Action.run_id == run_id).all()

            logging_utility.info("Found %d actions for run_id: %s", len(actions), run_id)
            return ActionList(actions=[ActionRead.model_validate(action) for action in actions])
        except Exception as e:
            logging_utility.error("Error listing actions for run: %s", str(e))
            raise HTTPException(status_code=500, detail="An error occurred while listing the actions for the run")

    def expire_actions(self) -> int:
        """Expire all actions that are past their expiration date."""
        logging_utility.info("Expiring outdated actions")
        try:
            now = datetime.now()
            expired_actions = self.db.query(Action).filter(Action.expires_at <= now, Action.is_processed == False).all()
            count = 0
            for action in expired_actions:
                action.status = "expired"
                self.db.commit()
                count += 1
            logging_utility.info("Expired %d actions", count)
            return count
        except Exception as e:
            self.db.rollback()
            logging_utility.error("Error expiring actions: %s", str(e))
            raise HTTPException(status_code=500, detail="An error occurred while expiring actions")

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
