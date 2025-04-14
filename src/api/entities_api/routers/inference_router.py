import asyncio
import json
import time
from typing import Any, AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from projectdavid_common import ValidationInterface
from projectdavid_common.utilities.logging_service import LoggingUtility

from entities_api.inference.inference_arbiter import InferenceArbiter
from entities_api.inference.inference_provider_selector import \
    InferenceProviderSelector

router = APIRouter()
logging_utility = LoggingUtility()


async def run_sync_generator_in_thread(
    sync_gen_func, *args, **kwargs
) -> AsyncGenerator[Any, None]:
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue(maxsize=10)
    finished_sentinel = object()

    def run_generator():
        try:
            sync_iterator = sync_gen_func(*args, **kwargs)
            for item in sync_iterator:
                future = asyncio.run_coroutine_threadsafe(queue.put(item), loop)
                future.result()
        except Exception as e:
            logging_utility.error(f"Error in sync generator thread: {e}", exc_info=True)
            future = asyncio.run_coroutine_threadsafe(queue.put(e), loop)
            try:
                future.result()
            except Exception as put_err:
                logging_utility.error(f"Error putting exception onto queue: {put_err}")
        finally:
            future = asyncio.run_coroutine_threadsafe(
                queue.put(finished_sentinel), loop
            )
            try:
                future.result()
            except Exception as put_err:
                logging_utility.error(f"Error putting sentinel onto queue: {put_err}")

    thread_task = loop.run_in_executor(None, run_generator)

    try:
        while True:
            item = await queue.get()
            if item is finished_sentinel:
                break
            elif isinstance(item, Exception):
                raise item
            else:
                yield item
            queue.task_done()
    finally:
        if not thread_task.done():
            thread_task.cancel()
        try:
            await asyncio.wait_for(thread_task, timeout=5.0)
        except asyncio.TimeoutError:
            logging_utility.warning(
                "Timeout waiting for sync generator thread to finish."
            )
        except asyncio.CancelledError:
            logging_utility.debug("Sync generator thread task cancelled.")


@router.post(
    "/completions",
    summary="Asynchronous completions streaming endpoint (New Architecture)",
    response_description="A stream of JSON-formatted completions chunks",
)
async def completions(
    stream_request: ValidationInterface.StreamRequest,
):
    log_payload = stream_request.dict()
    if "api_key" in log_payload and log_payload["api_key"]:
        log_payload["api_key"] = "****"  # Sanitize
    logging_utility.info(
        "Completions endpoint called with unified model_id: %s, payload: %s",
        stream_request.model,
        log_payload,
    )

    arbiter = InferenceArbiter()
    selector = InferenceProviderSelector(arbiter)

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

        logging_utility.info(
            "Starting stream_generator for model: %s, run_id: %s",
            stream_request.model,
            run_id,
        )

        yield "data: " + json.dumps({"status": "handshake"}) + "\n\n"
        await asyncio.sleep(0.01)
        yield "data: " + json.dumps({"status": "initializing"}) + "\n\n"
        await asyncio.sleep(0.01)

        try:
            sync_gen_args = {
                "thread_id": stream_request.thread_id,
                "message_id": stream_request.message_id,
                "run_id": run_id,
                "assistant_id": stream_request.assistant_id,
                "model": stream_request.model,
                "stream_reasoning": False,
                "api_key": stream_request.api_key,  # DO NOT VALIDATE — USER-PROVIDED
            }

            async for chunk in run_sync_generator_in_thread(
                general_handler_instance.process_conversation, **sync_gen_args
            ):
                idx += 1
                if chunk is None:
                    continue

                if isinstance(chunk, str):
                    try:
                        if chunk.strip().startswith(("{", "[")):
                            chunk_data = json.loads(chunk)
                        else:
                            chunk_data = {"type": "content", "content": chunk}
                    except json.JSONDecodeError:
                        chunk_data = {"type": "content", "content": chunk}
                elif isinstance(chunk, dict):
                    chunk_data = chunk
                else:
                    logging_utility.warning(
                        f"Skipping unknown chunk type: {type(chunk)}"
                    )
                    continue

                chunk_data.setdefault("type", "content")
                if "content" not in chunk_data and chunk_data.get("type") != "error":
                    chunk_data["content"] = ""

                yield "data: " + json.dumps(chunk_data) + "\n\n"
                await asyncio.sleep(0.01)

        except Exception as e:
            yield "data: " + json.dumps(
                {
                    "type": "error",
                    "error": "stream_failure",
                    "message": "An internal error occurred during stream generation.",
                }
            ) + "\n\n"
            logging_utility.error(
                "Stream generator error in run %s: %s", run_id, str(e), exc_info=True
            )
        finally:
            elapsed = time.time() - start_time
            logging_utility.info(
                "Stream processing finished for run_id: %s. Chunks yielded: %d. Duration: %.2f s",
                run_id,
                idx,
                elapsed,
            )
            yield "data: [DONE]\n\n"

    try:
        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream",
            headers={
                "X-Stream-Init": "true",
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
