import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, AsyncGenerator  # Import AsyncGenerator

from fastapi import APIRouter, HTTPException, Request  # Added Request
from fastapi.responses import StreamingResponse
from projectdavid_common import ValidationInterface
from projectdavid_common.utilities.logging_service import LoggingUtility

from entities_api.inference.inference_arbiter import InferenceArbiter
from entities_api.inference.inference_provider_selector import \
    InferenceProviderSelector

# Remove this - we will implement the bridging logic directly
# from entities_api.utils.wrap_sync_generator import async_wrap_sync_generator

router = APIRouter()
logging_utility = LoggingUtility()

# Optional: Configure a dedicated executor if needed, otherwise default is fine
# executor = ThreadPoolExecutor(max_workers=...)


async def run_sync_generator_in_thread(
    sync_gen_func, *args, **kwargs
) -> AsyncGenerator[Any, None]:
    """
    Runs a synchronous generator function in a thread pool and yields results asynchronously.
    """
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue(maxsize=10)  # Add a reasonable buffer size
    finished_sentinel = object()  # Unique object to signal completion

    def run_generator():
        try:
            # Call the actual synchronous generator function passed in
            sync_iterator = sync_gen_func(*args, **kwargs)
            for item in sync_iterator:
                # Put item onto queue; blocks if queue is full
                # Use run_coroutine_threadsafe as put is async
                future = asyncio.run_coroutine_threadsafe(queue.put(item), loop)
                future.result()  # Wait for put to complete (blocks this thread only)
        except Exception as e:
            logging_utility.error(f"Error in sync generator thread: {e}", exc_info=True)
            # Signal error to the async side
            future = asyncio.run_coroutine_threadsafe(queue.put(e), loop)
            try:
                future.result()
            except Exception as put_err:
                logging_utility.error(f"Error putting exception onto queue: {put_err}")
        finally:
            # Signal completion
            future = asyncio.run_coroutine_threadsafe(
                queue.put(finished_sentinel), loop
            )
            try:
                future.result()
            except Exception as put_err:
                logging_utility.error(f"Error putting sentinel onto queue: {put_err}")

    # Start the synchronous generator in a background thread
    # Pass the function and its arguments
    thread_task = loop.run_in_executor(None, run_generator)  # Use default executor

    try:
        while True:
            item = await queue.get()
            if item is finished_sentinel:
                logging_utility.debug(
                    "Received finished sentinel from sync generator thread."
                )
                break
            elif isinstance(item, Exception):
                logging_utility.error("Received exception from sync generator thread.")
                raise item  # Propagate the exception
            else:
                yield item
            queue.task_done()  # Mark item as processed
    finally:
        # Ensure the thread task is awaited/cancelled if the consumer stops early
        if not thread_task.done():
            thread_task.cancel()
            logging_utility.warning("Cancelled background thread for sync generator.")
        # Wait for thread task to complete or be cancelled
        try:
            await asyncio.wait_for(thread_task, timeout=5.0)  # Wait briefly for cleanup
        except asyncio.TimeoutError:
            logging_utility.warning(
                "Timeout waiting for sync generator thread task to finish."
            )
        except asyncio.CancelledError:
            logging_utility.debug("Sync generator thread task cancelled as expected.")


@router.post(
    "/completions",
    summary="Asynchronous completions streaming endpoint (New Architecture)",
    response_description="A stream of JSON-formatted completions chunks",
)
async def completions(
    stream_request: ValidationInterface.StreamRequest,
):  # Renamed for clarity
    """
    Streams inference output using Entities' modular handler architecture.
    This endpoint delegates to general and specific handlers for model routing.
    Sync generators from handlers are run in a thread pool to avoid blocking.
    """
    log_payload = stream_request.dict()
    if "api_key" in log_payload and log_payload["api_key"]:
        log_payload["api_key"] = "****"
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

    # -------------------------------
    # Streaming Logic (Using Thread Pool Bridge)
    # -------------------------------
    async def stream_generator():
        idx = 0
        start_time = time.time()
        run_id = stream_request.run_id  # Get run_id from request
        logging_utility.info(
            "Starting stream_generator for model: %s, run_id: %s",
            stream_request.model,
            run_id,
        )

        # Initial handshake messages
        yield "data: " + json.dumps({"status": "handshake"}) + "\n\n"
        await asyncio.sleep(0.01)  # Small sleep to allow messages to flush
        yield "data: " + json.dumps({"status": "initializing"}) + "\n\n"
        await asyncio.sleep(0.01)

        try:
            # Define arguments for the sync generator function
            sync_gen_args = {
                "thread_id": stream_request.thread_id,
                "message_id": stream_request.message_id,
                "run_id": run_id,
                "assistant_id": stream_request.assistant_id,
                "model": stream_request.model,
                "stream_reasoning": False,  # Or get from request if needed
                "api_key": stream_request.api_key,
            }

            # --- CRITICAL CHANGE: Use the thread pool bridge ---
            # Pass the *method* to call and its arguments
            async for chunk in run_sync_generator_in_thread(
                general_handler_instance.process_conversation, **sync_gen_args
            ):
                # --- END CRITICAL CHANGE ---

                idx += 1
                if chunk is None:  # Skip potential None values yielded by handler
                    continue

                # --- Chunk Normalization (Keep your existing logic) ---
                if isinstance(chunk, str):
                    try:
                        # Attempt to parse if it looks like JSON, otherwise treat as plain content
                        if chunk.strip().startswith(("{", "[")):
                            chunk_data = json.loads(chunk)
                        else:
                            chunk_data = {"type": "content", "content": chunk}
                    except json.JSONDecodeError:
                        # If JSON parsing fails, treat as plain content
                        logging_utility.warning(
                            f"Received string chunk that wasn't valid JSON: '{chunk[:100]}...'"
                        )
                        chunk_data = {"type": "content", "content": chunk}
                elif isinstance(chunk, dict):
                    chunk_data = chunk
                else:
                    logging_utility.warning(
                        f"Skipping unknown chunk type: {type(chunk)}"
                    )
                    continue  # Skip unknown types

                # Ensure essential keys exist
                chunk_data.setdefault("type", "content")
                # Add content key if missing and not an error chunk
                if "content" not in chunk_data and chunk_data.get("type") != "error":
                    chunk_data["content"] = ""  # Default to empty string
                # --- End Chunk Normalization ---

                yield "data: " + json.dumps(chunk_data) + "\n\n"
                await asyncio.sleep(0.01)  # Small delay between chunks

        except Exception as e:
            # Handle errors propagated from the sync generator thread or bridge
            error_msg = f"Stream generation failed: {str(e)}"
            logging_utility.error(
                "Stream generator error in run %s: %s",
                run_id,
                error_msg,
                exc_info=True,  # Log the full traceback
            )
            # Yield a final error message to the client
            yield "data: " + json.dumps(
                {
                    "type": "error",
                    "error": "stream_failure",
                    # Provide a slightly more generic message to client for security
                    "message": "An internal error occurred during stream generation.",
                }
            ) + "\n\n"
        finally:
            # This block always runs, ensuring [DONE] is sent
            elapsed = time.time() - start_time
            logging_utility.info(
                "Stream processing finished for run_id: %s. Chunks yielded: %d. Duration: %.2f s",
                run_id,
                idx,
                elapsed,
            )
            # Send the SSE standard completion signal
            yield "data: [DONE]\n\n"

    # -------------------------------
    # Response: SSE Streaming
    # -------------------------------
    try:
        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream",
            headers={
                "X-Stream-Init": "true",  # Custom header example
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "Content-Encoding": "none",  # Ensure no compression interferes
            },
        )
    except Exception as e:
        # Catch errors during StreamingResponse setup itself (less likely)
        logging_utility.error(
            "Fatal error setting up StreamingResponse for run %s: %s",
            stream_request.run_id,  # Use run_id from original request
            str(e),
            exc_info=True,
        )
        # Return a standard HTTP error if response setup fails
        raise HTTPException(status_code=500, detail="Stream initialization failed")
