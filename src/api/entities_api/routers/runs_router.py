from fastapi import APIRouter, Depends, HTTPException
from projectdavid_common import UtilsInterface, ValidationInterface
from pydantic import ValidationError
from sqlalchemy.orm import Session

from entities_api.dependencies import get_api_key, get_db
from entities_api.models.models import ApiKey as ApiKeyModel
from entities_api.services.runs import RunService

# Instantiate utilities.
ent_validator = ValidationInterface()
logging_utility = UtilsInterface.LoggingUtility()

# FastAPI router
router = APIRouter()


@router.post("/runs", response_model=ValidationInterface.Run)
def create_run(
    run: ValidationInterface.RunCreate,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(
        f"[{auth_key.user_id}] Creating run for thread {run.thread_id}"
    )
    run_service = RunService(db)
    try:
        new_run = run_service.create_run(run)
        logging_utility.info(f"Run created successfully: {new_run.id}")
        return new_run
    except HTTPException as e:
        logging_utility.error(f"HTTP error during run creation: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"Unexpected error during run creation: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.get("/runs/{run_id}", response_model=ValidationInterface.RunReadDetailed)
def get_run(
    run_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(f"[{auth_key.user_id}] Retrieving run ID: {run_id}")
    run_service = RunService(db)
    try:
        run = run_service.get_run(run_id)
        logging_utility.info(f"Run retrieved successfully: {run_id}")
        return run
    except HTTPException as e:
        logging_utility.error(f"HTTP error retrieving run {run_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"Unexpected error retrieving run {run_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.put("/runs/{run_id}/status", response_model=ValidationInterface.Run)
def update_run_status(
    run_id: str,
    status_update: ValidationInterface.RunStatusUpdate,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(
        f"[{auth_key.user_id}] Updating status of run {run_id} → {status_update.status}"
    )
    run_service = RunService(db)
    try:
        updated_run = run_service.update_run_status(run_id, status_update.status)
        logging_utility.info(f"Run status updated: {run_id}")
        return updated_run
    except ValidationError as e:
        logging_utility.error(f"Validation error for run {run_id}: {str(e)}")
        raise HTTPException(status_code=422, detail=f"Validation error: {e.errors()}")
    except HTTPException as e:
        logging_utility.error(f"HTTP error updating run {run_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"Unexpected error updating run {run_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.post("/runs/{run_id}/cancel", response_model=ValidationInterface.Run)
def cancel_run(
    run_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(f"[{auth_key.user_id}] Cancelling run {run_id}")
    run_service = RunService(db)
    try:
        cancelled_run = run_service.cancel_run(run_id)
        logging_utility.info(f"Run cancelled successfully: {run_id}")
        return cancelled_run
    except HTTPException as e:
        logging_utility.error(f"HTTP error cancelling run {run_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"Unexpected error cancelling run {run_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")
