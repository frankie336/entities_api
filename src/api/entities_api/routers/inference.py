import json
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from projectdavid_common import (
    ValidationInterface,
)  # Assuming StreamRequest has api_key field

# Make sure these imports point to the correct location of your classes
from entities_api.inference.inference_arbiter import InferenceArbiter
from entities_api.inference.inference_provider_selector import InferenceProviderSelector
from entities_api.services.logging_service import (
    LoggingUtility,
)  # Ensure this path is correct

router = APIRouter()
logging_utility = LoggingUtility()


@router.post(
    "/completions",
    summary="Asynchronous completions streaming endpoint",
    response_description="A stream of JSON-formatted completions chunks",
)
async def completions(
    request: ValidationInterface.StreamRequest,
):  # request object holds the parsed JSON body
    """
    Enhanced streaming endpoint with first-chunk stabilization and robust error handling.
    Passes the api_key from the request to the selected provider instance.
    """
    # Log the request, including the api_key presence if desired (be careful logging keys)
    log_payload = request.dict()
    if "api_key" in log_payload and log_payload["api_key"]:
        log_payload["api_key"] = "****"  # Mask the key in logs
    logging_utility.info(
        "Completions streaming endpoint called with payload: %s", log_payload
    )

    # Initialize arbiter and provider selector
    arbiter = InferenceArbiter()
    selector = InferenceProviderSelector(arbiter)

    try:
        logging_utility.info(
            "Selecting provider with provider=%s and model=%s",
            request.provider.value,  # Assuming provider is an Enum
            request.model,
        )
        # Provider selection logic remains the same
        provider_instance = selector.select_provider(
            provider=request.provider.value, model=request.model
        )
        logging_utility.info(
            "Provider selected successfully: %s", type(provider_instance).__name__
        )
    except ValueError as ve:
        logging_utility.error("Provider selection error: %s", str(ve), exc_info=True)
        raise HTTPException(status_code=400, detail=str(ve))

    def stream_chunks():
        idx = 0
        logging_utility.info(
            "Starting to stream chunks for thread_id=%s, run_id=%s",
            request.thread_id,
            request.run_id,
        )

        # Initial stabilization sequence
        yield "data: " + json.dumps({"status": "handshake"}) + "\n\n"
        yield "data: " + json.dumps({"status": "initializing"}) + "\n\n"

        try:
            # ---> MODIFICATION HERE <---
            # Pass the api_key from the request object to the provider's method
            chunk_generator = provider_instance.process_conversation(
                thread_id=request.thread_id,
                message_id=request.message_id,
                run_id=request.run_id,
                assistant_id=request.assistant_id,
                model=request.model,
                stream_reasoning=False,  # Keep original value unless specified otherwise
                api_key=request.api_key,  # Pass the key from the validated request payload
            )

            # --- The rest of the streaming logic remains unchanged ---
            first_chunk_sent = False
            last_heartbeat = time.time()

            for chunk in chunk_generator:
                current_time = time.time()
                idx += 1

                # Send heartbeat every 2 seconds until first real chunk
                if not first_chunk_sent and (current_time - last_heartbeat) > 2:
                    yield "data: " + json.dumps({"status": "processing"}) + "\n\n"
                    last_heartbeat = current_time

                try:
                    if chunk is None:
                        continue

                    # Normal chunk processing (Original logic)
                    chunk_data = {}
                    if isinstance(chunk, str):
                        try:
                            chunk_data = json.loads(chunk)
                        except json.JSONDecodeError:
                            chunk_data = {"content": chunk}
                    elif isinstance(chunk, dict):
                        chunk_data = chunk

                    if not isinstance(chunk_data, dict):
                        continue

                    if (
                        "content" not in chunk_data
                    ):  # Ensure minimum structure (Original logic)
                        chunk_data["content"] = ""

                    if not first_chunk_sent and chunk_data.get(
                        "content"
                    ):  # Mark first meaningful chunk (Original logic)
                        first_chunk_sent = True
                        chunk_data["first_chunk"] = True  # Add marker if needed

                    yield "data: " + json.dumps(chunk_data) + "\n\n"

                except Exception as inner_exc:
                    logging_utility.error(
                        "Chunk processing error: %s", str(inner_exc), exc_info=True
                    )  # Add exc_info
                    yield "data: " + json.dumps(
                        {"error": "chunk_processing_failed", "message": str(inner_exc)}
                    ) + "\n\n"

        except Exception as e:
            logging_utility.error(
                "Stream generator error in stream_chunks: %s", str(e), exc_info=True
            )  # Add exc_info
            yield "data: " + json.dumps(
                {"error": "stream_failure", "message": str(e)}
            ) + "\n\n"
        finally:
            logging_utility.info(
                "Stream completed for thread_id=%s, run_id=%s. Total chunks yielded (approx): %d",
                request.thread_id,
                request.run_id,
                idx,
            )
            yield "data: [DONE]\n\n"  # Ensure correct SSE termination

    try:
        # Return the streaming response using the generator function
        return StreamingResponse(
            stream_chunks(),
            media_type="text/event-stream",
            headers={
                "X-Stream-Init": "true",  # Custom header from original code
                "Cache-Control": "no-cache, no-transform",  # Standard SSE headers
                "Connection": "keep-alive",  # Standard SSE headers
            },
        )
    except Exception as e:
        # Catch errors during StreamingResponse creation itself (less likely)
        logging_utility.error(
            "Fatal error setting up StreamingResponse: %s", str(e), exc_info=True
        )
        raise HTTPException(status_code=500, detail="Stream initialization failed")
