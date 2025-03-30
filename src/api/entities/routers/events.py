# Presumed location: Your FastAPI application's router file for event handling

import asyncio
import json
import logging  # Using standard logging

from entities_common import UtilsInterface
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse  # For SSE endpoint

# --- Core Entities Imports (Adjust paths as needed) ---
# Assuming EventMonitoringService is correctly implemented as discussed previously
from entities.services.event_handler_service import EventMonitoringService
# --- SSE Manager Import (Adjust path as needed) ---
# Assuming sse_manager.py is in the same directory or accessible via path
from entities.services.sse_manager import SSEManager

# Assuming EntitiesInternalInterface is used *within* EventMonitoringService if needed


logging_utility = UtilsInterface.LoggingUtility()

# Configure logging elsewhere in your app setup if needed (level, handler, format)
logging.basicConfig(level=logging.INFO) # Basic config for demonstration

# Create a single, shared instance of the SSE Manager
sse_manager = SSEManager()

# Define the FastAPI router with a prefix
router = APIRouter()


# --- Request Models ---
class MonitorRequest(BaseModel):
    run_id: str


# --- API Endpoints ---

# 1. Endpoint to REGISTER monitoring (Client calls this first)
@router.post("/monitor", status_code=200) # Use specific status code
async def register_run_monitoring(payload: MonitorRequest):
    """
    Registers a run_id for server-side event monitoring.
    This triggers the EventMonitoringService to start watching the run internally.
    Does NOT stream events itself.
    """
    run_id = payload.run_id
    logging_utility.info(f"Received monitor registration request for run_id: {run_id}")
    try:
        # Instantiate the service, passing the shared sse_manager instance
        # The EventMonitoringService __init__ should accept sse_manager
        monitor_service = EventMonitoringService(sse_manager=sse_manager)

        # Start the internal monitoring process.
        # This method should ideally check if the run exists internally
        # and raise ValueError or similar if not found, to prevent race conditions.
        # Assuming start() is synchronous for now, but endpoint is async for best practice.
        monitor_service.start(run_id=run_id)

        logging_utility.info(f"Successfully registered and started internal monitoring for run_id: {run_id}")
        # Return a simple success confirmation
        return {"status": "monitoring_registered", "run_id": run_id}

    except ValueError as ve:
        # Catch specific "Not Found" or validation errors raised by monitor_service.start()
        logging_utility.warning(f"Failed to register monitoring for run {run_id}: {ve}")
        # Return 404 if the run wasn't found to start monitoring
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        # Catch any other unexpected errors during registration/start
        logging_utility.error(f"Error registering run monitor for {run_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error registering monitor: {str(e)}")


# 2. Endpoint to SUBSCRIBE to events (Client connects here AFTER registering)
@router.get("/subscribe/{run_id}")
async def subscribe_to_run_events(run_id: str, request: Request):
    """
    Client connects here using Server-Sent Events (SSE) to receive
    real-time events for a specific, previously registered run_id.
    """
    logging_utility.info(f"SSE: Client requesting subscription for run_id: {run_id}")

    # Create a unique queue for this client connection
    subscriber_queue = asyncio.Queue()
    # Register this queue with the manager for the specific run_id
    await sse_manager.add_subscriber(run_id, subscriber_queue)

    async def event_generator():
        """Generates SSE messages from the queue for this client."""
        try:
            # Optional: Send an initial confirmation event to the client
            yield f"event: connected\ndata: {json.dumps({'run_id': run_id, 'message': 'Subscription active'})}\n\n"
            logging_utility.info(f"SSE: Connection active for run_id: {run_id}")

            while True:
                # Crucial: Check if the client has disconnected
                if await request.is_disconnected():
                    logging_utility.info(f"SSE: Client disconnected for run_id: {run_id}. Closing generator.")
                    break # Exit the loop if client is gone

                # Wait for a message from the SSEManager's broadcast
                try:
                    # Use a timeout to periodically check for disconnection
                    # and potentially send keep-alives
                    message = await asyncio.wait_for(subscriber_queue.get(), timeout=30.0)
                    yield message # Send the pre-formatted message from the manager
                    subscriber_queue.task_done() # Acknowledge processing
                except asyncio.TimeoutError:
                    # No message received in timeout window, send a keep-alive comment
                    # This helps prevent proxies/clients from closing the connection
                    yield ": keep-alive\n\n"
                    continue # Continue the loop to wait again

        except asyncio.CancelledError:
             logging_utility.info(f"SSE: Event generator task cancelled for run_id: {run_id}")
             # This happens if the server shuts down or the task is force-cancelled
        finally:
            # CRITICAL Clean-up: Remove the subscriber queue from the manager
            # This happens when the client disconnects or the generator exits for any reason
            await sse_manager.remove_subscriber(run_id, subscriber_queue)
            logging_utility.info(f"SSE: Cleaned up subscriber and queue for run_id: {run_id}")

    # Return the streaming response using the generator
    return EventSourceResponse(event_generator())
