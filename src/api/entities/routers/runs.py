from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from entities.dependencies import get_db
from entities.schemas.runs import Run as RunSchema, RunCreate, RunStatusUpdate
from entities.services.logging_service import LoggingUtility
from entities.services.run_service import RunService

router = APIRouter()
logging_utility = LoggingUtility()


@router.post("/runs", response_model=RunSchema)
def create_run(run: RunCreate, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to create a new run for thread ID: {run.thread_id}")
    run_service = RunService(db)
    try:
        new_run = run_service.create_run(run)
        logging_utility.info(f"Run created successfully with ID: {new_run.id}")
        return new_run
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while creating run: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while creating run: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.get("/runs/{run_id}", response_model=RunSchema)
def get_run(run_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to get run with ID: {run_id}")
    run_service = RunService(db)
    try:
        run = run_service.get_run(run_id)
        logging_utility.info(f"Run retrieved successfully with ID: {run_id}")
        return run
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while retrieving run {run_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while retrieving run {run_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.put("/runs/{run_id}/status", response_model=RunSchema)
def update_run_status(run_id: str, status_update: RunStatusUpdate, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to update status of run ID: {run_id} to {status_update.status}")

    run_service = RunService(db)

    try:
        # Update the run status using the service layer
        updated_run = run_service.update_run_status(run_id, status_update.status)
        logging_utility.info(f"Run status updated successfully for run ID: {run_id}")
        return updated_run

    except ValidationError as e:
        logging_utility.error(f"Validation error for run ID: {run_id}, error: {str(e)}")
        raise HTTPException(status_code=422, detail=f"Validation error: {e.errors()}")

    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while updating run status for run ID: {run_id}: {str(e)}")
        raise e

    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while updating run status for run ID: {run_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.post("/runs/{run_id}/cancel", response_model=RunSchema)
def cancel_run(run_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to cancel run with ID: {run_id}")
    run_service = RunService(db)
    try:
        cancelled_run = run_service.cancel_run(run_id)
        logging_utility.info(f"Run cancelled successfully with ID: {run_id}")
        return cancelled_run
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while cancelling run {run_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while cancelling run {run_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")