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
    Optimized Bridge: Runs a synchronous generator in a separate thread and
    pumps data into the async event loop using zero-latency fire-and-forget queuing
    with built-in backpressure handling.
    """
    loop = asyncio.get_running_loop()
    # 512 is the 'shock absorber'. It can hold ~500 tokens/chunks before
    # the worker thread is asked to slow down.
    queue = asyncio.Queue(maxsize=512)
    finished_sentinel = object()

    def run_generator():
        try:
            for item in sync_gen_func(*args, **kwargs):
                if loop.is_closed():
                    break

                # --- BACKPRESSURE TWEAK ---
                # Before we schedule the 'put', we check if the queue is full.
                # This prevents the thread from overwhelming the Event Loop/Memory
                # if the client's internet connection is slow.
                while not loop.is_closed():
                    if queue.qsize() < 512:
                        # Schedule the put on the loop as soon as possible (fire-and-forget)
                        loop.call_soon_threadsafe(queue.put_nowait, item)
                        break
                    else:
                        # Queue is full: Client is slow.
                        # We sleep the worker thread for 10ms to allow the loop to drain.
                        time.sleep(0.01)

        except Exception as e:
            logging_utility.error(f"Error in sync generator thread: {e}", exc_info=True)
            if not loop.is_closed():
                loop.call_soon_threadsafe(queue.put_nowait, e)
        finally:
            if not loop.is_closed():
                loop.call_soon_threadsafe(queue.put_nowait, finished_sentinel)

    # Execute the synchronous generator in the default ThreadPoolExecutor
    thread_task = loop.run_in_executor(None, run_generator)

    try:
        while True:
            # The async consumer waits here for items.
            # Because queue.get() is async, the main thread is free to handle
            # other requests while waiting for the next LLM token.
            item = await queue.get()

            if item is finished_sentinel:
                break
            if isinstance(item, Exception):
                raise item

            yield item

    except Exception as e:
        logging_utility.warning(f"Streaming connection terminated: {e}")
        # Note: We don't need to manually 'raise' here if using StreamingResponse,
        # but we do want to ensure we stop the generator.
        raise
    finally:
        # Cleanup: Check if the thread task is still running
        if not thread_task.done():
            # We can't kill a sync thread, but the 'if loop.is_closed()' check
            # inside run_generator will eventually cause it to exit.
            pass


@router.post(
    "/completions",
    summary="Asynchronous completions streaming endpoint (Unified Orchestration)",
    response_description="A stream of JSON-formatted completions chunks",
)
async def completions(
    stream_request: ValidationInterface.StreamRequest, redis: Redis = Depends(get_redis)
):
    """Handles streaming completion requests using the appropriate inference provider."""
    # ... (Logging logic kept same) ...
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
        # Pre-calculate the prefix and suffix to avoid f-string overhead in tight loop
        prefix = "data: "
        suffix = "\n\n"

        # Pre-construct the base_workers dict to avoid recreating it if possible
        # (Only useful if we aren't parsing incoming JSON)

        idx = 0
        error_occurred = False
        # --------------------------
        # The inbound payload here!
        # ---------------------------
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
                idx += 1
                if chunk is None:
                    continue

                # --- OPTIMIZED JSON HANDLING ---
                # Avoid json.loads + json.dumps cycle if possible.

                final_json_str = ""

                if isinstance(chunk, dict):
                    # It's already a dict, just add the run_id and dump once.
                    if "type" not in chunk:
                        chunk["type"] = "content"
                        chunk["content"] = ""  # Normalize empty content
                    chunk["run_id"] = run_id
                    final_json_str = json.dumps(chunk)

                elif isinstance(chunk, str):
                    # OPTIMIZATION: If it starts with {, it's likely a JSON string.
                    # We have to parse it to inject run_id safely.
                    if chunk.strip().startswith("{"):
                        try:
                            data = json.loads(chunk)
                            data["run_id"] = run_id
                            if "type" not in data:
                                data["type"] = "content"
                            final_json_str = json.dumps(data)
                        except json.JSONDecodeError:
                            # Fallback: Treat as raw content string
                            final_json_str = json.dumps(
                                {"type": "content", "content": chunk, "run_id": run_id}
                            )
                    else:
                        # Raw string content (no parsing needed)
                        final_json_str = json.dumps(
                            {"type": "content", "content": chunk, "run_id": run_id}
                        )
                else:
                    # Fallback for unknown types
                    final_json_str = json.dumps(
                        {"type": "content", "content": str(chunk), "run_id": run_id}
                    )

                yield f"{prefix}{final_json_str}{suffix}"

                # REMOVED: await asyncio.sleep(0.001)
                # ^^^ This was the main cause of lag.
                # The 'await queue.get()' inside the generator acts as the context switch.

        except Exception as e:
            error_occurred = True
            logging_utility.error(f"Stream loop error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'run_id': run_id, 'message': str(e)})}\n\n"
        finally:
            elapsed = time.time() - start_time
            if not error_occurred:
                yield "data: [DONE]\n\n"

            # Log summary (Moved to debug/info to reduce noise if needed)
            logging_utility.info(f"Stream finished: {idx} chunks in {elapsed:.2f}s")

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
