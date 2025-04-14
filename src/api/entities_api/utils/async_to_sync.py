import asyncio
from typing import AsyncGenerator, Generator


def async_to_sync_stream(agen: AsyncGenerator[str, None]) -> Generator[str, None, None]:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def runner():
        async for item in agen:
            yield item

    gen = runner()

    try:
        while True:
            yield loop.run_until_complete(gen.__anext__())
    except StopAsyncIteration:
        pass
    finally:
        loop.close()
