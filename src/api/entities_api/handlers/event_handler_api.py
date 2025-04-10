# event_handler_api.py
from typing import Any, List

from common.services.logging_service import LoggingUtility
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from entities_api.services.event_handler import EntitiesEventHandler

# Initialize logging and the main client.
logging_utility = LoggingUtility()


def handle_event(event_type: str, event_data: Any):
    """
    Global event callback that logs events.
    Extend this callback to add further processing if needed.
    """
    logging_utility.info(f"[Callback] Event: {event_type}, Data: {event_data}")
    # Additional event handling logic can be added here.


# Initialize the event handler with the client services and callback.
event_handler = EntitiesEventHandler(
    run_service=client.run_service,
    action_service=client.action_client,
    event_callback=handle_event,
)


# Pydantic models for request payloads.
class MonitorRequest(BaseModel):
    run_id: str = Field(..., description="The ID of the run to monitor")


class StopMonitorRequest(BaseModel):
    run_id: str = Field(..., description="The ID of the run to stop monitoring")


# Create the FastAPI app.
app = FastAPI(title="Event Handler API", version="1.0.0")


@app.post("/api/events/start-monitor", summary="Start monitoring a run")
def start_monitor(request: MonitorRequest):
    """
    Starts event monitoring for the provided run ID.
    """
    run_id = request.run_id.strip()
    if not run_id:
        raise HTTPException(status_code=400, detail="run_id must not be empty")

    try:
        event_handler.start_monitoring(run_id)
        logging_utility.info(f"Monitoring started for run: {run_id}")
        return {"message": f"Monitoring started for run: {run_id}"}
    except Exception as e:
        logging_utility.error(f"Error starting monitor for run {run_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error starting monitor for run {run_id}"
        )


@app.post("/api/events/stop-monitor", summary="Stop monitoring a run")
def stop_monitor(request: StopMonitorRequest):
    """
    Stops event monitoring for the provided run ID.
    """
    run_id = request.run_id.strip()
    if not run_id:
        raise HTTPException(status_code=400, detail="run_id must not be empty")

    try:
        event_handler.stop_monitoring(run_id)
        logging_utility.info(f"Monitoring stopped for run: {run_id}")
        return {"message": f"Monitoring stopped for run: {run_id}"}
    except Exception as e:
        logging_utility.error(f"Error stopping monitor for run {run_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error stopping monitor for run {run_id}"
        )


@app.get("/api/events/active", summary="List active monitors")
def get_active_monitors():
    """
    Returns a list of run IDs that are currently being monitored.
    """
    active_monitors: List[str] = list(event_handler.active_monitors.keys())
    return {"active_monitors": active_monitors}
