from fastapi import APIRouter, Depends, HTTPException

# Import validators and utilities from your common package.
from projectdavid_common import UtilsInterface, ValidationInterface
from pydantic import ValidationError
from sqlalchemy.orm import Session

from entities_api.dependencies import get_db
from entities_api.services.runs import RunService

# Instantiate our utilities.
ent_validator = ValidationInterface()
logging_utility = UtilsInterface.LoggingUtility()

# Initialize the FastAPI router.
router = APIRouter()


@router.post("/runs", response_model=ValidationInterface.Run)
def create_run(run: ValidationInterface.RunCreate, db: Session = Depends(get_db)):
    logging_utility.info(
        f"Received request to create a new run for thread ID: {run.thread_id}"
    )
    run_service = RunService(db)
    try:
        new_run = run_service.create_run(run)
        logging_utility.info(f"Run created successfully with ID: {new_run.id}")
        return new_run  # Now returns a full Run model.
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while creating run: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(
            f"An unexpected error occurred while creating run: {str(e)}"
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.get("/runs/{run_id}", response_model=ValidationInterface.RunReadDetailed)
def get_run(run_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to get run with ID: {run_id}")
    run_service = RunService(db)
    try:
        run = run_service.get_run(run_id)
        logging_utility.info(f"Run retrieved successfully with ID: {run_id}")
        return run  # Returns a RunReadDetailed model.
    except HTTPException as e:
        logging_utility.error(
            f"HTTP error occurred while retrieving run {run_id}: {str(e)}"
        )
        raise e
    except Exception as e:
        logging_utility.error(
            f"An unexpected error occurred while retrieving run {run_id}: {str(e)}"
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.put("/runs/{run_id}/status", response_model=ValidationInterface.Run)
def update_run_status(
    run_id: str,
    status_update: ValidationInterface.RunStatusUpdate,
    db: Session = Depends(get_db),
):
    logging_utility.info(
        f"Received request to update status of run ID: {run_id} to {status_update.status}"
    )
    run_service = RunService(db)
    try:
        # Validate and update the run status.
        updated_run = run_service.update_run_status(run_id, status_update.status)
        logging_utility.info(f"Run status updated successfully for run ID: {run_id}")
        return updated_run  # Returns the updated Run.
    except ValidationError as e:
        logging_utility.error(f"Validation error for run ID: {run_id}, error: {str(e)}")
        raise HTTPException(status_code=422, detail=f"Validation error: {e.errors()}")
    except HTTPException as e:
        logging_utility.error(
            f"HTTP error occurred while updating run status for run ID: {run_id}: {str(e)}"
        )
        raise e
    except Exception as e:
        logging_utility.error(
            f"An unexpected error occurred while updating run status for run ID: {run_id}: {str(e)}"
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.post("/runs/{run_id}/cancel", response_model=ValidationInterface.Run)
def cancel_run(run_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to cancel run with ID: {run_id}")
    run_service = RunService(db)
    try:
        cancelled_run = run_service.cancel_run(run_id)
        logging_utility.info(f"Run cancelled successfully with ID: {run_id}")
        return cancelled_run  # Returns the cancelled Run.
    except HTTPException as e:
        logging_utility.error(
            f"HTTP error occurred while cancelling run {run_id}: {str(e)}"
        )
        raise e
    except Exception as e:
        logging_utility.error(
            f"An unexpected error occurred while cancelling run {run_id}: {str(e)}"
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")
