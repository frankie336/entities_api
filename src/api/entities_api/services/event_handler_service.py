# src/api/entities_api/services/event_handler_service.py

import logging  # Use standard logging

from projectdavid import Entity

# Assuming this is correctly implemented and handles async callbacks potentially
from entities_api.services.event_handler import EntitiesEventHandler

# Import the SSE Manager (adjust path as needed)
from entities_api.services.sse_manager import (  # Assuming sse_manager.py is accessible
    SSEManager,
)

# Assuming entities_sdk.src.entities_api.services.logging_service defines LoggingUtility
# If not, adjust or use standard logging directly
# from entities_api.services.logging_service import LoggingUtility

# Use standard Python logging - configure it in your FastAPI app setup
logger = logging.getLogger(__name__)


class EventMonitoringService:
    """
    Monitors run events internally using EntitiesEventHandler and broadcasts
    them to subscribed clients via SSEManager.
    """

    def __init__(self, sse_manager: SSEManager, event_callback=None):
        """
        Initializes the service.

        Args:
            sse_manager: An instance of the shared SSEManager for broadcasting.
            event_callback: An optional synchronous callback for additional server-side logic.
        """
        if not sse_manager:
            # SSEManager is crucial for the primary function (broadcasting)
            raise ValueError(
                "SSEManager instance must be provided to EventMonitoringService"
            )

        self.client = Entity()  # Internal client for data access
        self._sse_manager = sse_manager  # Store the SSE manager instance
        self._external_callback = event_callback  # Optional external hook

        # Pass the *internal* async handler to the event handler
        self._event_handler = EntitiesEventHandler(
            run_service=self.client.runs,  # Assuming these are needed by EventHandler
            action_service=self.client.actions,  # Assuming these are needed by EventHandler
            event_callback=self._handle_event,  # Pass the internal async method
        )
        logger.debug("EventMonitoringService initialized.")

    def start(self, run_id: str):
        """
        Starts the internal monitoring process for the given run_id.
        Checks if the run exists before starting.

        Args:
            run_id: The ID of the run to monitor.

        Raises:
            ValueError: If the run_id is not found internally.
            Exception: If any other error occurs during run retrieval or monitor start.
        """
        logger.info(f"Attempting to start event monitoring for run {run_id}")

        # --- Prevent Race Condition: Check if run exists ---
        try:
            # Use your internal client's method to get run details.
            # Replace 'retrieve' with the actual method name if different.
            # This call should ideally return the run object or raise an error/return None if not found.
            run_object = self.client.runs.retrieve_run(run_id=run_id)
            if not run_object:
                # Log clearly and raise a specific error the API endpoint can catch
                logger.warning(
                    f"Cannot start monitoring: Run {run_id} not found via internal client."
                )
                raise ValueError(f"Run '{run_id}' not found.")
            else:
                logger.debug(f"Run {run_id} confirmed to exist internally.")

        except Exception as e:
            # Catch potential errors from the internal client during retrieval
            logger.error(
                f"Error checking existence for run {run_id}: {e}", exc_info=True
            )
            # Re-raise the exception to signal failure to the caller (API endpoint)
            raise

        # --- Start the actual internal monitoring ---
        try:
            # This call likely starts a background task/thread within EntitiesEventHandler
            self._event_handler.start_monitoring(run_id)
            logger.info(
                f"✅ Successfully initiated internal monitoring handler for run {run_id}"
            )
        except Exception as e:
            logger.error(
                f"Error calling _event_handler.start_monitoring for run {run_id}: {e}",
                exc_info=True,
            )
            # Re-raise to signal failure
            raise

    async def _handle_event(self, event_type: str, event_data: dict):
        """
        Internal async callback invoked by EntitiesEventHandler when a run event occurs.
        It logs the event, broadcasts it via SSEManager, and calls any external callback.

        IMPORTANT: EntitiesEventHandler MUST be capable of calling this async callback
        correctly (e.g., using asyncio.create_task if the event handler itself runs
        synchronously or in a different thread).

        Args:
            event_type: The type of the event (e.g., 'tool_invoked', 'run_ended').
            event_data: The dictionary payload associated with the event.
        """
        # Try to extract run_id, essential for broadcasting
        run_id = event_data.get("run_id") if isinstance(event_data, dict) else None
        if not run_id:
            # If run_id isn't directly in event_data, try 'id' as a fallback for some event types
            run_id = event_data.get("id") if isinstance(event_data, dict) else None

        logger.info(
            f"[🔔 Internal Event Received] Run: {run_id or 'Unknown'}, Type: {event_type}"
        )
        logger.debug(f"Event Data for {run_id or 'Unknown'}: {event_data}")

        # --- Broadcast via SSE ---
        if run_id:
            try:
                # SSEManager handles JSON serialization and formatting
                await self._sse_manager.broadcast_event(run_id, event_type, event_data)
                logger.debug(
                    f"Broadcasted event '{event_type}' for run {run_id} via SSE."
                )
            except Exception as e:
                # Log errors during broadcasting but don't necessarily stop processing
                logger.error(
                    f"Failed to broadcast SSE event for run {run_id}: {e}",
                    exc_info=True,
                )
        else:
            logger.warning(
                f"Cannot broadcast event '{event_type}': run_id missing in event_data."
            )

        # --- Optional: Handle external synchronous callback ---
        # This part remains synchronous if the callback itself is synchronous.
        if self._external_callback:
            logger.debug(f"Checking external callback for event type: {event_type}")
            # Example: Only call external callback for specific types if needed
            if event_type in [
                "tool_invoked",
                "action_required",
            ]:  # Add other types if necessary
                try:
                    logger.info(
                        f"Executing external synchronous callback for event '{event_type}' for run {run_id or 'Unknown'}."
                    )
                    self._external_callback(event_type, event_data)
                except Exception as e:
                    logger.error(
                        f"Error executing external callback for run {run_id or 'Unknown'}, event {event_type}: {e}",
                        exc_info=True,
                    )

        # --- Specific Logging based on type (optional enhancement) ---
        if event_type == "run_ended":
            logger.info(f"Run {run_id} processing internally marked as ended.")
        elif event_type == "error":
            logger.error(f"Run {run_id} encountered an error (details in event data).")
