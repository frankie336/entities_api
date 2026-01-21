import asyncio
from typing import AsyncGenerator, Generator, TypeVar

T = TypeVar('T')


def async_to_sync_stream(agen: AsyncGenerator[T, None]) -> Generator[T, None, None]:
    """
    Convert async generator to sync generator with proper streaming.

    CRITICAL: Uses a persistent event loop and non-blocking iteration
    to ensure chunks are yielded immediately as they arrive.
    """
    # Check if there's already a running event loop
    try:
        loop = asyncio.get_running_loop()
        # We're in an async context, can't use this approach
        raise RuntimeError("Cannot use async_to_sync_stream in async context")
    except RuntimeError:
        # No running loop, create a new one
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    # Create an async iterator
    aiter = agen.__aiter__()

    try:
        while True:
            # Get the next coroutine without blocking other operations
            try:
                # run_until_complete blocks, but we need it for each individual item
                # The key is that we yield immediately after getting each item
                item = loop.run_until_complete(aiter.__anext__())
                yield item
            except StopAsyncIteration:
                break
    finally:
        # Clean up the loop
        try:
            # Cancel any pending tasks
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()

            # Run the loop one more time to handle cancellations
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        except Exception:
            pass
        finally:
            loop.close()


# Alternative implementation using queue (if the above doesn't fix it)
def async_to_sync_stream_queue(agen: AsyncGenerator[T, None]) -> Generator[T, None, None]:
    """
    Alternative implementation using a queue for better streaming.
    Use this if the simple version still has lag.
    """
    import queue
    import threading

    q: queue.Queue = queue.Queue(maxsize=1)  # Small queue for immediate streaming
    exception_holder = [None]

    def async_runner():
        """Run the async generator in a separate thread."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def consume():
            try:
                async for item in agen:
                    q.put(item)
            except Exception as e:
                exception_holder[0] = e
            finally:
                q.put(StopIteration)

        try:
            loop.run_until_complete(consume())
        finally:
            loop.close()

    # Start the async consumer in background thread
    thread = threading.Thread(target=async_runner, daemon=True)
    thread.start()

    # Yield items as they arrive
    while True:
        item = q.get()  # Blocks until item available

        if item is StopIteration:
            break

        if exception_holder[0]:
            raise exception_holder[0]

        yield item

    thread.join(timeout=1.0)
