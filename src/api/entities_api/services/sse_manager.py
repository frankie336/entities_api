import asyncio
import json
import logging
from collections import defaultdict
from typing import Any, Dict, List

logger = logging.getLogger(__name__)
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
            sse_subscribers[run_id].remove(queue)
            logger.debug(
                f"SSEManager: Removed subscriber for {run_id}. Remaining: {len(sse_subscribers[run_id])}"
            )
            if not sse_subscribers[run_id]:
                del sse_subscribers[run_id]
                logger.info(
                    f"SSEManager: No subscribers remaining for {run_id}. Removed entry."
                )
        except KeyError:
            logger.warning(
                f"SSEManager: Attempted to remove subscriber for non-existent run_id entry: {run_id}"
            )
        except ValueError:
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
            logger.debug(
                f"SSEManager: No active subscribers for run_id {run_id} to broadcast event '{event_type}'."
            )
            return
        subscribers = sse_subscribers[run_id]
        if not subscribers:
            logger.debug(
                f"SSEManager: Subscriber list for run_id {run_id} is empty (should have been cleaned up)."
            )
            return
        logger.info(
            f"SSEManager: Broadcasting event '{event_type}' to {len(subscribers)} subscriber(s) for run_id: {run_id}"
        )
        try:
            json_data = json.dumps(event_data)
        except TypeError as e:
            logger.error(
                f"SSEManager: Failed to serialize event data to JSON for run_id {run_id}. Event: {event_type}. Data: {event_data}. Error: {e}"
            )
            return
        message = f"event: {event_type}\ndata: {json_data}\n\n"
        for queue in list(subscribers):
            try:
                await queue.put(message)
            except Exception as e:
                logger.error(
                    f"SSEManager: Error putting message into a subscriber queue for run_id {run_id}. Error: {e}"
                )
