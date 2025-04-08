# File: sse_manager.py
# Purpose: Manages Server-Sent Event (SSE) connections and broadcasts events.

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any, Dict, List

# Use standard Python logging. Configure it in your main application setup.
logger = logging.getLogger(__name__)

# --- Module-level storage for subscribers ---
# Using defaultdict simplifies adding the first subscriber for a run_id.
# Key: run_id (str)
# Value: List of asyncio.Queue objects, one for each connected client listening for that run_id.
# This dictionary needs to be accessed and modified by async functions,
# but the dictionary operations themselves are generally considered thread/task-safe
# for CPython when adding/removing keys or lists. Appending/removing from the list
# associated with a key is also generally safe if managed correctly (no concurrent iteration/modification).
# Using asyncio.Queue ensures safe communication between the broadcaster and listeners.
sse_subscribers: Dict[str, List[asyncio.Queue]] = defaultdict(list)


class SSEManager:
    """
    Manages Server-Sent Event subscriptions and facilitates broadcasting messages
    to clients subscribed to specific run_ids.
    """

    async def add_subscriber(self, run_id: str, queue: asyncio.Queue):
        """
        Registers a client's queue to receive events for a specific run_id.

        Args:
            run_id: The identifier of the run the client is subscribing to.
            queue: The asyncio.Queue instance associated with the client's connection.
        """
        logger.info(f"SSEManager: Adding subscriber queue for run_id: {run_id}")
        sse_subscribers[run_id].append(queue)
        logger.debug(
            f"SSEManager: Current subscribers for {run_id}: {len(sse_subscribers[run_id])}"
        )

    async def remove_subscriber(self, run_id: str, queue: asyncio.Queue):
        """
        Unregisters a client's queue, typically when the client disconnects.

        Args:
            run_id: The identifier of the run the client was subscribed to.
            queue: The asyncio.Queue instance to remove.
        """
        logger.info(f"SSEManager: Removing subscriber queue for run_id: {run_id}")
        try:
            # Find and remove the specific queue for this client
            sse_subscribers[run_id].remove(queue)
            logger.debug(
                f"SSEManager: Removed subscriber for {run_id}. Remaining: {len(sse_subscribers[run_id])}"
            )

            # If no clients are left listening for this run_id, clean up the entry
            if not sse_subscribers[run_id]:
                del sse_subscribers[run_id]
                logger.info(
                    f"SSEManager: No subscribers remaining for {run_id}. Removed entry."
                )

        except KeyError:
            # This can happen if the run_id entry was already removed (e.g., race condition on disconnect)
            logger.warning(
                f"SSEManager: Attempted to remove subscriber for non-existent run_id entry: {run_id}"
            )
        except ValueError:
            # This can happen if the specific queue was already removed
            logger.warning(
                f"SSEManager: Attempted to remove a queue instance not found for run_id: {run_id}"
            )

    async def broadcast_event(
        self, run_id: str, event_type: str, event_data: Dict[str, Any]
    ):
        """
        Formats an event and puts it into the queues of all clients subscribed to the run_id.

        Args:
            run_id: The identifier of the run the event pertains to.
            event_type: The 'event' field for the SSE message.
            event_data: A dictionary containing the event payload (must be JSON-serializable).
        """
        if run_id not in sse_subscribers:
            # No clients are currently listening for this run, so do nothing.
            logger.debug(
                f"SSEManager: No active subscribers for run_id {run_id} to broadcast event '{event_type}'."
            )
            return

        subscribers = sse_subscribers[run_id]
        if not subscribers:
            logger.debug(
                f"SSEManager: Subscriber list for run_id {run_id} is empty (should have been cleaned up)."
            )
            return  # Should not happen if cleanup is correct, but safe check

        logger.info(
            f"SSEManager: Broadcasting event '{event_type}' to {len(subscribers)} subscriber(s) for run_id: {run_id}"
        )

        try:
            # Ensure data is JSON serializable before broadcasting
            json_data = json.dumps(event_data)
        except TypeError as e:
            logger.error(
                f"SSEManager: Failed to serialize event data to JSON for run_id {run_id}. Event: {event_type}. Data: {event_data}. Error: {e}"
            )
            return  # Cannot send unserializable data

        # Format the message according to the Server-Sent Events specification.
        # Each message block ends with two newlines (\n\n).
        message = f"event: {event_type}\ndata: {json_data}\n\n"

        # Iterate through a copy of the list in case the list is modified concurrently
        # although adding/removing subscribers should happen in separate tasks.
        for queue in list(subscribers):  # Iterate over a copy
            try:
                # Put the pre-formatted message string into the client's queue.
                # The corresponding SSE endpoint task will read from this queue.
                await queue.put(message)
            except Exception as e:
                # Log if putting into a specific client's queue fails
                # (This usually shouldn't happen with asyncio.Queue unless it's full, which needs handling)
                logger.error(
                    f"SSEManager: Error putting message into a subscriber queue for run_id {run_id}. Error: {e}"
                )
                # Decide if you need to remove this subscriber if putting fails repeatedly.
