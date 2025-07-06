import asyncio


async def async_wrap_sync_generator(sync_gen):
    for item in sync_gen:
        yield item
        await asyncio.sleep(0)
