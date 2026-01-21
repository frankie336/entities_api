# src/api/entities_api/routers/inference_router.py
import asyncio
import json
import time
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from projectdavid_common import ValidationInterface
from projectdavid_common.utilities.logging_service import LoggingUtility
from redis import Redis

from entities_api.orchestration.engine.inference_arbiter import InferenceArbiter
from entities_api.orchestration.engine.inference_provider_selector import (
    InferenceProviderSelector,
)
from src.api.entities_api.dependencies import get_redis

router = APIRouter()
logging_utility = LoggingUtility()


async def run_sync_generator_in_thread(
    sync_gen_func, *args, **kwargs
) -> AsyncGenerator[Any, None]:
    """
    Runs a synchronous generator function in a separate thread.
    Includes high-velocity buffering and robust backpressure handling.
    """
    loop = asyncio.get_running_loop()
    # Increase buffer size to handle high-speed reasoning bursts (e.g. R1)
    queue = asyncio.Queue(maxsize=512)
    finished_sentinel = object()

    def run_generator():
        try:
            for item in sync_gen_func(*args, **kwargs):
                if loop.is_closed():
                    break

                # We schedule the put into the async queue.
                # result() blocks the WORKER thread until the item is accepted.
                # If the queue is full (512 items), this thread naturally waits (backpressure).
                # Removed the 10s timeout to prevent crashes during heavy DB/Network I/O.
                future = asyncio.run_coroutine_threadsafe(queue.put(item), loop)
                try:
                    future.result()
                except Exception:
                    break

        except Exception as e:
            logging_utility.error(f"Error in sync generator thread: {e}", exc_info=True)
            if not loop.is_closed():
                asyncio.run_coroutine_threadsafe(queue.put(e), loop)
        finally:
            if not loop.is_closed():
                asyncio.run_coroutine_threadsafe(queue.put(finished_sentinel), loop)

    # Run in the default ThreadPoolExecutor
    thread_task = loop.run_in_executor(None, run_generator)

    try:
        while True:
            item = await queue.get()
            if item is finished_sentinel:
                logging_utility.debug(
                    "Received finished sentinel from sync generator thread."
                )
                break
            if isinstance(item, Exception):
                logging_utility.error(
                    f"Rethrowing exception from sync generator thread: {item}"
                )
                raise item
            yield item
    except Exception as e:
        logging_utility.error(
            f"Error encountered while consuming from generator queue: {e}",
            exc_info=True,
        )
        raise
    finally:
        if not thread_task.done():
            logging_utility.warning(
                "Sync generator thread still running, attempting cancellation."
            )
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
    log_payload = stream_request.dict()
    if log_payload.get("api_key"):
        log_payload["api_key"] = (
            f"***{log_payload['api_key'][-4:]}"
            if len(log_payload.get("api_key", "")) > 4
            else "***"
        )
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
        idx = 0
        start_time = time.time()
        run_id = stream_request.run_id
        error_occurred = False

        try:
            sync_gen_args = {
                "thread_id": stream_request.thread_id,
                "message_id": stream_request.message_id,
                "run_id": run_id,
                "assistant_id": stream_request.assistant_id,
                "model": stream_request.model,
                "stream_reasoning": True,
                "api_key": stream_request.api_key,
            }

            async for chunk in run_sync_generator_in_thread(
                general_handler_instance.process_conversation, **sync_gen_args
            ):
                idx += 1
                if chunk is None:
                    continue

                # Standardize chunk data
                if isinstance(chunk, str):
                    if chunk.strip().startswith(("{", "[")):
                        try:
                            chunk_data = json.loads(chunk)
                        except json.JSONDecodeError:
                            chunk_data = {"type": "content", "content": chunk}
                    else:
                        chunk_data = {"type": "content", "content": chunk}
                else:
                    chunk_data = chunk

                chunk_data.setdefault("type", "content")
                if "content" not in chunk_data and chunk_data.get("type") not in (
                    "error",
                    "status",
                ):
                    chunk_data["content"] = ""

                chunk_data["run_id"] = run_id
                yield f"data: {json.dumps(chunk_data)}\n\n"

                # Tiny sleep to allow the event loop to breathe and handle I/O
                await asyncio.sleep(0.001)

        except Exception as e:
            error_occurred = True
            logging_utility.error(
                f"Stream loop error in run {run_id}: {e}", exc_info=True
            )
            yield f"data: {json.dumps({'type': 'error', 'run_id': run_id, 'message': str(e)})}\n\n"
        finally:
            elapsed = time.time() - start_time
            logging_utility.info(
                "Stream finished for run %s. Chunks: %d. Duration: %.2fs. Error: %s",
                run_id,
                idx,
                elapsed,
                error_occurred,
            )
            if not error_occurred:
                yield "data: [DONE]\n\n"

    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
