import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from projectdavid_common import UtilsInterface
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from entities_api.dependencies import get_api_key
from entities_api.models.models import ApiKey as ApiKeyModel
from entities_api.services.event_handler_service import EventMonitoringService
from entities_api.services.sse_manager import SSEManager

logging_utility = UtilsInterface.LoggingUtility()
logging.basicConfig(level=logging.INFO)
sse_manager = SSEManager()
router = APIRouter()


class MonitorRequest(BaseModel):
    run_id: str


@router.post("/monitor", status_code=200)
async def register_run_monitoring(
    payload: MonitorRequest, auth_key: ApiKeyModel = Depends(get_api_key)
):
    """
    Registers a run_id for server-side event monitoring.
    Requires a valid API key.
    """
    run_id = payload.run_id
    logging_utility.info(
        f"User '{auth_key.user_id}' - Received monitor registration request for run_id: {run_id}"
    )
    try:
        monitor_service = EventMonitoringService(sse_manager=sse_manager)
        monitor_service.start(run_id=run_id)
        logging_utility.info(
            f"User '{auth_key.user_id}' - Successfully registered and started internal monitoring for run_id: {run_id}"
        )
        return {"status": "monitoring_registered", "run_id": run_id}
    except ValueError as ve:
        logging_utility.warning(
            f"User '{auth_key.user_id}' - Failed to register monitoring for run {run_id}: {ve}"
        )
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        logging_utility.error(
            f"User '{auth_key.user_id}' - Error registering run monitor for {run_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error registering monitor: {str(e)}",
        )


@router.get("/subscribe/{run_id}")
async def subscribe_to_run_events(
    run_id: str, request: Request, auth_key: ApiKeyModel = Depends(get_api_key)
):
    """
    Client connects here using Server-Sent Events (SSE) to receive
    real-time events for a specific run_id. Requires a valid API key.
    """
    logging_utility.info(
        f"User '{auth_key.user_id}' - SSE: Client requesting subscription for run_id: {run_id}"
    )

    subscriber_queue = asyncio.Queue()
    await sse_manager.add_subscriber(run_id, subscriber_queue)

    async def event_generator():
        try:
            yield f"event: connected\ndata: {json.dumps({'run_id': run_id, 'message': 'Subscription active'})}\n\n"
            logging_utility.info(
                f"User '{auth_key.user_id}' - SSE: Connection active for run_id: {run_id}"
            )

            while True:
                if await request.is_disconnected():
                    logging_utility.info(
                        f"User '{auth_key.user_id}' - SSE: Client disconnected for run_id: {run_id}. Closing generator."
                    )
                    break

                try:
                    message = await asyncio.wait_for(
                        subscriber_queue.get(), timeout=30.0
                    )
                    yield message
                    subscriber_queue.task_done()
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue

        except asyncio.CancelledError:
            logging_utility.info(
                f"User '{auth_key.user_id}' - SSE: Event generator task cancelled for run_id: {run_id}"
            )
        finally:
            await sse_manager.remove_subscriber(run_id, subscriber_queue)
            logging_utility.info(
                f"User '{auth_key.user_id}' - SSE: Cleaned up subscriber and queue for run_id: {run_id}"
            )

    return EventSourceResponse(event_generator())
