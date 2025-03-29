from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from entities.dependencies import get_db
from entities.schemas.actions import ActionUpdate, ActionCreate
from entities.schemas.actions import ActionRead
from entities.services.actions import ActionService
from entities.services.logging_service import LoggingUtility

router = APIRouter()
logging_utility = LoggingUtility()


@router.post("/actions", response_model=ActionRead)
def create_action(action: ActionCreate, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to create a new action.")
    action_service = ActionService(db)
    try:
        new_action = action_service.create_action(action)
        logging_utility.info(f"Action created successfully with ID: {new_action.id}")
        return new_action
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while creating action: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while creating action: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.get("/actions/{action_id}", response_model=ActionRead)
def get_action(action_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to get action with ID: {action_id}")
    action_service = ActionService(db)
    try:
        action = action_service.get_action(action_id)
        logging_utility.info(f"Action retrieved successfully with ID: {action_id}")
        return action
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while retrieving action {action_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while retrieving action {action_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.put("/actions/{action_id}", response_model=ActionRead)
def update_action_status(action_id: str, action_update: ActionUpdate, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to update status of action ID: {action_id}")
    action_service = ActionService(db)
    try:
        updated_action = action_service.update_action_status(action_id, action_update)
        logging_utility.info(f"Action status updated successfully for action ID: {action_id}")
        return updated_action
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while updating action status {action_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while updating action status {action_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.get("/runs/{run_id}/actions/status", response_model=List[ActionRead])
def get_actions_by_status(run_id: str, status: Optional[str] = "pending", db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to get actions for run ID: {run_id} with status: {status}")
    action_service = ActionService(db)
    try:
        actions = action_service.get_actions_by_status(run_id, status)
        logging_utility.info(f"Actions retrieved successfully for run ID: {run_id} with status: {status}")
        return actions
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while retrieving actions for run {run_id} with status {status}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while retrieving actions for run {run_id} with status {status}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.get("/actions/pending/{run_id}", response_model=List[Dict[str, Any]])
def get_pending_actions(
    run_id: str,  # Accept run_id as part of the URL path
    db: Session = Depends(get_db)
):
    """
    Retrieve all pending actions with their function arguments, tool names,
    and run details. Filter by run_id.
    """
    logging_utility.info(f"Received request to list pending actions for run_id: {run_id}")
    action_service = ActionService(db)
    try:
        # Assuming `get_pending_actions` only uses the `run_id` parameter
        pending_actions = action_service.get_pending_actions(run_id)
        logging_utility.info(f"Successfully retrieved {len(pending_actions)} pending action(s) for run_id: {run_id}.")
        return pending_actions
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while listing pending actions: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while listing pending actions: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.delete("/actions/{action_id}", status_code=204)
def delete_action(action_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to delete action with ID: {action_id}")
    action_service = ActionService(db)
    try:
        action_service.delete_action(action_id)
        logging_utility.info(f"Action deleted successfully with ID: {action_id}")
        return {"detail": "Action deleted successfully"}
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while deleting action {action_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while deleting action {action_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")
