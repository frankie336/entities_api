import asyncio
import json
import time
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from projectdavid_common import ValidationInterface
from projectdavid_common.utilities.logging_service import LoggingUtility
from redis import Redis

from src.api.entities_api.dependencies import get_redis
from src.api.entities_api.inference_mixin.inference_arbiter import InferenceArbiter
from src.api.entities_api.inference_mixin.inference_provider_selector import (
    InferenceProviderSelector,
)

router = APIRouter()
logging_utility = LoggingUtility()


async def run_sync_generator_in_thread(
    sync_gen_func, *args, **kwargs
) -> AsyncGenerator[Any, None]:
    """Runs a synchronous generator function in a separate thread."""
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue(maxsize=20)
    finished_sentinel = object()

    def run_generator():
        try:
            for item in sync_gen_func(*args, **kwargs):
                asyncio.run_coroutine_threadsafe(queue.put(item), loop).result(
                    timeout=10
                )
        except Exception as e:
            logging_utility.error(f"Error in sync generator thread: {e}", exc_info=True)
            asyncio.run_coroutine_threadsafe(queue.put(e), loop).result(timeout=1)
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(finished_sentinel), loop).result(
                timeout=1
            )

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
                "Sync generator thread still running after loop exit, attempting cancellation."
            )
            thread_task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(thread_task), timeout=1.0)
            except asyncio.TimeoutError:
                logging_utility.warning(
                    "Timeout waiting for sync generator thread to finish after cancellation."
                )
            except asyncio.CancelledError:
                logging_utility.debug("Sync generator thread task cleanly cancelled.")
            except Exception as final_e:
                logging_utility.error(
                    f"Error during final thread task cleanup: {final_e}", exc_info=True
                )


@router.post(
    "/completions",
    summary="Asynchronous completions streaming endpoint (New Architecture)",
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
        "Completions endpoint called with unified model_id: %s, payload: %s",
        stream_request.model,
        log_payload,
    )
    try:
        arbiter = InferenceArbiter(redis=redis)
        selector = InferenceProviderSelector(arbiter)
    except Exception as init_err:
        logging_utility.error(
            "Fatal error initializing InferenceArbiter/Selector: %s",
            str(init_err),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Internal server error during inference setup."
        )
    try:
        general_handler_instance, api_model_name = selector.select_provider(
            model_id=stream_request.model
        )
        logging_utility.info(
            "General handler selected: %s (for API model: %s)",
            type(general_handler_instance).__name__,
            api_model_name,
        )
    except ValueError as ve:
        logging_utility.error("Provider selection error: %s", str(ve), exc_info=True)
        status_code = 400 if "Invalid or unknown model identifier" in str(ve) else 500
        raise HTTPException(status_code=status_code, detail=str(ve))
    except Exception as e:
        logging_utility.error(
            "Unexpected error during provider selection: %s", str(e), exc_info=True
        )
        raise HTTPException(
            status_code=500, detail="Internal server error during provider setup."
        )

    async def stream_generator():
        idx = 0
        start_time = time.time()
        run_id = stream_request.run_id
        error_occurred = False
        logging_utility.info(
            "Starting stream_generator for model: %s, run_id: %s",
            stream_request.model,
            run_id,
        )
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
                chunk_data = None
                if isinstance(chunk, str):
                    if chunk.strip().startswith(("{", "[")):
                        try:
                            chunk_data = json.loads(chunk)
                        except json.JSONDecodeError:
                            logging_utility.warning(
                                f"Received string chunk resembling JSON but failed to parse: {chunk[:100]}..."
                            )
                            chunk_data = {"type": "content", "content": chunk}
                    else:
                        chunk_data = {"type": "content", "content": chunk}
                elif isinstance(chunk, dict):
                    chunk_data = chunk
                else:
                    logging_utility.warning(
                        f"Skipping unknown chunk type from generator: {type(chunk)}"
                    )
                    continue
                chunk_data.setdefault("type", "content")
                if "content" not in chunk_data and chunk_data.get("type") not in (
                    "error",
                    "status",
                ):
                    chunk_data["content"] = ""
                chunk_data["run_id"] = run_id
                yield f"data: {json.dumps(chunk_data)}\n\n"
                await asyncio.sleep(0.01)
        except Exception as e:
            error_occurred = True
            logging_utility.error(
                "Stream generator loop error in run %s: %s",
                run_id,
                str(e),
                exc_info=True,
            )
            error_payload = json.dumps(
                {
                    "type": "error",
                    "run_id": run_id,
                    "error": "stream_generation_failed",
                    "message": f"An internal error occurred during stream generation: {str(e)}",
                }
            )
            yield f"data: {error_payload}\n\n"
        finally:
            elapsed = time.time() - start_time
            logging_utility.info(
                "Stream processing finished for run_id: %s. Chunks yielded: %d. Duration: %.2f s. Error Occurred: %s",
                run_id,
                idx,
                elapsed,
                error_occurred,
            )
            if not error_occurred:
                yield "data: [DONE]\n\n"

    try:
        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream",
            headers={
                "X-Accel-Buffering": "no",
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "Content-Encoding": "none",
            },
        )
    except Exception as e:
        logging_utility.error(
            "Fatal error setting up StreamingResponse for run %s: %s",
            stream_request.run_id,
            str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Stream initialization failed")
