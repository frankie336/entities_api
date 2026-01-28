import asyncio
import queue
import threading
from typing import AsyncGenerator, Generator, TypeVar

T = TypeVar("T")

# Sentinel object to mark the end of the stream (Singleton)
# Using a unique object is faster than checking tuple status on every chunk.
_DONE = object()


def async_to_sync_stream(agen: AsyncGenerator[T, None]) -> Generator[T, None, None]:
    """
    True Streaming Bridge: Runs the async stream in a continuous background thread.

    Optimizations:
    1. Uses a Sentinel Object (_DONE) to avoid tuple packing/unpacking overhead per token.
    2. Daemon thread ensures cleanup if the main process dies.
    """
    # Use a thread-safe queue.
    # maxsize acts as backpressure: if the network is faster than the user,
    # it buffers 100 items and then pauses the network download until the user catches up.
    q = queue.Queue(maxsize=100)

    def _producer():
        """
        Runs in a separate thread.
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def consume_stream():
            try:
                async for item in agen:
                    # OPTIMIZATION: Put raw item directly
                    q.put(item)
            except Exception as e:
                # Pass exceptions to the main thread
                q.put(e)
            finally:
                # Signal completion
                q.put(_DONE)

        try:
            loop.run_until_complete(consume_stream())
        finally:
            loop.close()

    # 1. Start the connection in the background immediately
    t = threading.Thread(target=_producer, daemon=True)
    t.start()

    # 2. Consume items the moment they hit the queue
    while True:
        # Blocks here until the first token arrives (TTFT)
        item = q.get()

        if item is _DONE:
            break

        # Check if the item is actually an exception passed from the thread
        if isinstance(item, Exception):
            raise item

        yield item
