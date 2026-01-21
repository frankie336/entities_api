import asyncio
import queue
import threading
from typing import AsyncGenerator, Generator, TypeVar

T = TypeVar("T")


def async_to_sync_stream(agen: AsyncGenerator[T, None]) -> Generator[T, None, None]:
    """
    True Streaming Bridge: Runs the async stream in a continuous background thread.
    This prevents 'Stop-and-Go' latency during the SSL Handshake and generation.
    """
    # Use a thread-safe queue to bridge the async worker and sync consumer
    # maxsize=100 provides a healthy buffer if the consumer is slower than the network
    q = queue.Queue(maxsize=100)

    # Sentinel objects to mark stream events
    NEXT_ITEM = object()
    DONE = object()

    def _producer():
        """
        Runs in a separate thread.
        Maintains a healthy, continuous event loop for the connection.
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def consume_stream():
            try:
                # The connection is established and maintained continuously here
                async for item in agen:
                    q.put((NEXT_ITEM, item))
            except Exception as e:
                # Pass exceptions (like connection errors) to the main thread
                q.put((NEXT_ITEM, e))
            finally:
                q.put((DONE, None))

        try:
            loop.run_until_complete(consume_stream())
        finally:
            loop.close()

    # 1. Start the connection in the background immediately
    t = threading.Thread(target=_producer, daemon=True)
    t.start()

    # 2. Consume items the moment they hit the queue
    while True:
        status, item = q.get()

        if status is DONE:
            break

        if isinstance(item, Exception):
            raise item

        yield item
