import asyncio  # Added for potential async operations in streaming
import json
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from projectdavid_common import ValidationInterface

# Logging utility
from projectdavid_common.utilities.logging_service import (
    LoggingUtility,
)  # Adjusted path based on previous examples

# Make sure these imports point to the correct location of your classes
from entities_api.inference.inference_arbiter import InferenceArbiter  # Keep arbiter

# Import the selector implementing the new logic
from entities_api.inference.inference_provider_selector import InferenceProviderSelector

router = APIRouter()
logging_utility = LoggingUtility()

# --- Initialize Arbiter (Singleton Pattern Recommended) ---
# It's better to initialize the arbiter once rather than per request
# You can use FastAPI's dependency injection or a simple global instance
# For simplicity here, we'll create it per request, but consider optimizing.
# arbiter_instance = InferenceArbiter() # Example: If initialized globally


@router.post(
    "/completions",
    summary="Asynchronous completions streaming endpoint (New Architecture)",
    response_description="A stream of JSON-formatted completions chunks",
)
async def completions(
    request: ValidationInterface.StreamRequest,
):
    """
    Streaming endpoint aligned with the two-level handler architecture.
    Selects a general handler, which then dispatches to a specific child handler.
    Passes api_key down the chain.
    """
    log_payload = request.dict()
    if "api_key" in log_payload and log_payload["api_key"]:
        log_payload["api_key"] = "****"
    # Use request.model which holds the unified ID (e.g., "hyperbolic/deepseek-ai/DeepSeek-R1")
    logging_utility.info(
        "Completions endpoint called with unified model_id: %s, payload: %s",
        request.model,
        log_payload,
    )

    # --- Initialize Dependencies ---
    # Consider using FastAPI dependency injection for these
    arbiter = InferenceArbiter()  # Or use singleton: arbiter = arbiter_instance
    selector = InferenceProviderSelector(arbiter)

    try:
        logging_utility.info(
            "Selecting provider using unified model_id: %s", request.model
        )
        # --- MODIFICATION 1: Selector Call ---
        # Pass only the unified model ID. It returns the GENERAL handler instance
        # and the API-specific name (which child handlers might use via _get_model_map)
        general_handler_instance, api_model_name = selector.select_provider(
            model_id=request.model
        )
        # Note: api_model_name is returned but not directly passed into process_conversation here,
        # assuming child handlers use _get_model_map internally based on the unified model ID.
        logging_utility.info(
            "General handler selected: %s (for API model: %s)",
            type(general_handler_instance).__name__,
            api_model_name,  # Log the resolved API name for clarity
        )
    except ValueError as ve:
        logging_utility.error("Provider selection error: %s", str(ve), exc_info=True)
        # Use 400 for bad request (e.g., unknown model ID) or 500 if it's a config error
        status_code = 400 if "Invalid or unknown model identifier" in str(ve) else 500
        raise HTTPException(status_code=status_code, detail=str(ve))
    except Exception as e:
        # Catch other unexpected errors during selection/instantiation
        logging_utility.error(
            "Unexpected error during provider selection: %s", str(e), exc_info=True
        )
        raise HTTPException(
            status_code=500, detail="Internal server error during provider setup."
        )

    # Define the async generator for streaming chunks
    async def stream_generator() -> (
        asyncio.StreamReader
    ):  # Use correct Generator type hint if possible
        idx = 0
        start_time = time.time()
        logging_utility.info(
            "Starting stream_generator for model: %s, run_id: %s",
            request.model,
            request.run_id,
        )

        # Initial handshake/stabilization remains the same
        yield "data: " + json.dumps({"status": "handshake"}) + "\n\n"
        await asyncio.sleep(0.01)  # Tiny sleep to allow client processing
        yield "data: " + json.dumps({"status": "initializing"}) + "\n\n"
        await asyncio.sleep(0.01)

        try:
            # --- MODIFICATION 2: Calling the General Handler ---
            # Call the method on the general_handler_instance.
            # Pass the original unified request.model as the 'model' parameter
            # so the general handler can use it for internal dispatching.
            chunk_iterator = general_handler_instance.process_conversation(
                thread_id=request.thread_id,
                message_id=request.message_id,
                run_id=request.run_id,
                assistant_id=request.assistant_id,
                model=request.model,  # Pass the UNIFIED ID here
                stream_reasoning=False,  # Or request.stream_reasoning if available
                api_key=request.api_key,
                # Pass other relevant parameters from the request if needed
                # e.g., temperature=request.temperature, max_tokens=request.max_tokens
                # **request.dict(exclude_unset=True) # Careful with passing everything
            )

            # --- Streaming Logic (mostly unchanged) ---
            first_chunk_sent = False
            last_heartbeat = time.time()

            # Use 'async for' as process_conversation returns an async generator
            async for chunk in chunk_iterator:
                current_time = time.time()
                idx += 1

                # Heartbeat logic
                if not first_chunk_sent and (current_time - last_heartbeat) > 2:
                    yield "data: " + json.dumps({"status": "processing"}) + "\n\n"
                    await asyncio.sleep(0.01)
                    last_heartbeat = current_time

                # Chunk processing
                try:
                    if chunk is None:
                        continue

                    chunk_data = {}
                    if isinstance(chunk, str):
                        try:
                            chunk_data = json.loads(chunk)
                        except json.JSONDecodeError:
                            chunk_data = {
                                "type": "content",
                                "content": chunk,
                            }  # Default type
                    elif isinstance(chunk, dict):
                        chunk_data = chunk
                    else:
                        continue  # Skip unexpected chunk types

                    # Ensure basic structure
                    if not chunk_data.get("type"):
                        chunk_data["type"] = "content"  # Default type
                    if (
                        "content" not in chunk_data
                        and "error" not in chunk_data
                        and chunk_data.get("type") != "status"
                    ):
                        chunk_data["content"] = (
                            ""  # Add empty content if missing and not error/status
                        )

                    # Mark first chunk containing actual content or a specific type
                    meaningful_chunk = chunk_data.get("content") or chunk_data.get(
                        "type"
                    ) not in [
                        "status",
                        "heartbeat",
                        "reasoning",
                    ]  # Define "meaningful"
                    if not first_chunk_sent and meaningful_chunk:
                        first_chunk_sent = True
                        chunk_data["first_chunk"] = True  # Optional marker

                    yield "data: " + json.dumps(chunk_data) + "\n\n"
                    await asyncio.sleep(0.01)  # Small yield point

                except Exception as inner_exc:
                    logging_utility.error(
                        "Chunk processing error in run %s: %s",
                        request.run_id,
                        str(inner_exc),
                        exc_info=True,
                    )
                    yield "data: " + json.dumps(
                        {
                            "type": "error",
                            "error": "chunk_processing_failed",
                            "message": str(inner_exc),
                        }
                    ) + "\n\n"
                    await asyncio.sleep(0.01)

        except Exception as e:
            # Catch errors from the chunk_iterator setup or during its execution
            logging_utility.error(
                "Stream generator error in run %s: %s",
                request.run_id,
                str(e),
                exc_info=True,
            )
            # Ensure error is JSON serializable
            error_message = f"Stream generation failed: {str(e)}"
            yield "data: " + json.dumps(
                {"type": "error", "error": "stream_failure", "message": error_message}
            ) + "\n\n"
            await asyncio.sleep(0.01)
        finally:
            elapsed = time.time() - start_time
            logging_utility.info(
                "Stream completed for run_id: %s. Chunks: %d. Duration: %.2f s",
                request.run_id,
                idx,
                elapsed,
            )
            # Ensure correct SSE termination signal
            yield "data: [DONE]\n\n"

    # Return the streaming response
    try:
        return StreamingResponse(
            stream_generator(),  # Pass the async generator directly
            media_type="text/event-stream",
            headers={
                "X-Stream-Init": "true",
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
            },
        )
    except Exception as e:
        logging_utility.error(
            "Fatal error setting up StreamingResponse for run %s: %s",
            request.run_id,
            str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Stream initialization failed")
