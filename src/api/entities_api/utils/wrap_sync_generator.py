# -------------------------------
# Utility: Wrap a sync generator for async streaming
# -------------------------------
# This allows `async for` to consume sync `yield`-based handlers
# without converting the entire handler architecture to async.
import asyncio


async def async_wrap_sync_generator(sync_gen):
    for item in sync_gen:
        yield item
        await asyncio.sleep(0)  # Cooperative multitasking
