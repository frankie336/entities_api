import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from projectdavid_common import UtilsInterface, ValidationInterface
from projectdavid_common.schemas.enums import StatusEnum
from pydantic import ValidationError
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse
from starlette import status

from entities_api.dependencies import get_api_key, get_db
from entities_api.models.models import ApiKey as ApiKeyModel
from entities_api.services.actions_service import ActionService
from entities_api.services.runs_service import RunService

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
    user_id = auth_key.user_id
    logging_utility.info("[%s] Creating run for thread %s", user_id, run.thread_id)

    run_service = RunService(db)
    try:
        new_run = run_service.create_run(run, user_id=user_id)
        logging_utility.info("Run created successfully: %s", new_run.id)
        return new_run

    except HTTPException as e:
        logging_utility.error("HTTP error during run creation: %s", str(e))
        raise
    except Exception as e:
        logging_utility.error("Unexpected error during run creation: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )


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


@router.get(
    "/runs/{run_id}/events",
    summary="Stream run‑lifecycle events (SSE)",
    response_class=EventSourceResponse,
    response_model=None,
)
async def stream_run_events(
    request: Request,
    run_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    run_svc = RunService(db)
    action_svc = ActionService(db)

    async def event_generator():
        while True:
            if await request.is_disconnected():
                break

            run = run_svc.get_run(run_id)
            if not run:
                yield {"event": "error", "data": '{"msg":"run not found"}'}
                break

            if run.status == StatusEnum.pending_action:
                pending = action_svc.get_pending_actions(run_id)
                if pending:
                    for act in pending:
                        data = act.dict() if hasattr(act, "dict") else act
                        yield {
                            "event": "action_required",
                            "data": json.dumps(data),
                        }
                    break

            await asyncio.sleep(0.5)

    return EventSourceResponse(event_generator())
