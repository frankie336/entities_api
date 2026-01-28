import asyncio
import json
import time
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from projectdavid_common import ValidationInterface
from projectdavid_common.utilities.logging_service import LoggingUtility
from redis import Redis

from entities_api.orchestration.engine.inference_arbiter import \
    InferenceArbiter
from entities_api.orchestration.engine.inference_provider_selector import \
    InferenceProviderSelector
from src.api.entities_api.dependencies import get_redis

router = APIRouter()
logging_utility = LoggingUtility()


async def run_sync_generator_in_thread(
    sync_gen_func, *args, **kwargs
) -> AsyncGenerator[Any, None]:
    """
    Runs a synchronous generator in a separate thread with NON-BLOCKING buffering.
    Optimized for high-throughput streaming.
    """
    loop = asyncio.get_running_loop()
    # Increased buffer size to handle bursts without blocking the producer thread
    queue = asyncio.Queue(maxsize=1024)
    finished_sentinel = object()

    def run_generator():
        try:
            # Cache scheduling functions to avoid attribute lookup cost in tight loop
            schedule = asyncio.run_coroutine_threadsafe
            put = queue.put

            for item in sync_gen_func(*args, **kwargs):
                if loop.is_closed():
                    break

                # OPTIMIZATION 1: Fire and Forget.
                # We do NOT call .result(). This allows the generator to sprint ahead
                # filling the buffer without waiting for the Event Loop to wake up.
                # Backpressure is handled naturally by queue.put (it will block if full).
                schedule(put(item), loop)

        except Exception as e:
            logging_utility.error(f"Error in sync generator thread: {e}", exc_info=True)
            if not loop.is_closed():
                asyncio.run_coroutine_threadsafe(queue.put(e), loop)
        finally:
            if not loop.is_closed():
                asyncio.run_coroutine_threadsafe(queue.put(finished_sentinel), loop)

    # Start the thread
    thread_task = loop.run_in_executor(None, run_generator)

    try:
        while True:
            # Wait for at least one item
            item = await queue.get()

            if item is finished_sentinel:
                break
            if isinstance(item, Exception):
                raise item

            yield item

            # OPTIMIZATION 3: Burst Flushing (Micro-Batching)
            # If the thread has produced more items while we were awaiting/processing,
            # grab them ALL now to send in one network packet.
            # This reduces Event Loop context switching overhead significantly.
            while not queue.empty():
                try:
                    next_item = queue.get_nowait()
                    if next_item is finished_sentinel:
                        # Put it back to ensure cleaner exit logic on next outer loop iteration
                        await queue.put(finished_sentinel)
                        break
                    yield next_item
                except asyncio.QueueEmpty:
                    break

    except Exception:
        # If the consumer (client) disconnects, we cancel the producer
        thread_task.cancel()
        raise
    finally:
        if not thread_task.done():
            thread_task.cancel()


@router.post(
    "/completions",
    summary="Asynchronous completions streaming endpoint (Unified Orchestration)",
    response_description="A stream of JSON-formatted completions chunks",
)
async def completions(
    stream_request: ValidationInterface.StreamRequest, redis: Redis = Depends(get_redis)
):
    """Handles streaming completion requests using the appropriate inference provider."""

    logging_utility.info(
        "Completions endpoint called for model: %s, run: %s",
        stream_request.model,
        stream_request.run_id,
    )

    try:
        arbiter = InferenceArbiter(redis=redis)
        selector = InferenceProviderSelector(arbiter)
        general_handler_instance, api_model_name = selector.select_provider(
            model_id=stream_request.model
        )
    except Exception as e:
        logging_utility.error(f"Provider setup failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    async def stream_generator():
        start_time = time.time()
        run_id = stream_request.run_id
        prefix = "data: "
        suffix = "\n\n"

        chunk_count = 0
        error_occurred = False

        try:
            sync_gen_args = {
                "thread_id": stream_request.thread_id,
                "message_id": stream_request.message_id,
                "run_id": run_id,
                "assistant_id": stream_request.assistant_id,
                "model": stream_request.model,
                "stream_reasoning": False,
                "api_key": stream_request.api_key,
            }

            async for chunk in run_sync_generator_in_thread(
                general_handler_instance.process_conversation, **sync_gen_args
            ):
                chunk_count += 1
                if chunk is None:
                    continue

                # OPTIMIZATION 2: Pass-Through Mode
                # We assume the Worker has already formatted valid JSON with run_id.
                # This avoids expensive json.loads() -> modify -> json.dumps().

                final_str = ""

                if isinstance(chunk, str):
                    # FAST PATH: It's a string. Trust it. Send it.
                    final_str = chunk
                elif isinstance(chunk, dict):
                    # SLOW PATH: Logic fallback if worker yields dicts
                    if "run_id" not in chunk:
                        chunk["run_id"] = run_id
                    final_str = json.dumps(chunk)
                else:
                    # Fallback for unknown types
                    final_json_str = json.dumps(
                        {"type": "content", "content": str(chunk), "run_id": run_id}
                    )
                    final_str = final_json_str

                yield f"{prefix}{final_str}{suffix}"

        except Exception as e:
            error_occurred = True
            logging_utility.error(f"Stream loop error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'run_id': run_id, 'message': str(e)})}\n\n"
        finally:
            elapsed = time.time() - start_time
            if not error_occurred:
                yield "data: [DONE]\n\n"

            # Log summary
            logging_utility.info(f"Stream finished: {chunk_count} chunks in {elapsed:.2f}s")

    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Standard SSE headers
            "Content-Type": "text/event-stream",
            "Transfer-Encoding": "chunked",
        },
    )
