import json
import time
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from entities_api.inference.inference_arbiter import InferenceArbiter
from entities_api.inference.inference_provider_selector import InferenceProviderSelector
from entities_api.schemas.inference import StreamRequest
from entities_api.services.logging_service import LoggingUtility

router = APIRouter()
logging_utility = LoggingUtility()


@router.post(
    "/completions",
    summary="Asynchronous completions streaming endpoint",
    response_description="A stream of JSON-formatted completions chunks"
)
async def completions(request: StreamRequest):
    """
    Enhanced streaming endpoint with first-chunk stabilization and robust error handling
    """
    logging_utility.info("Completions streaming endpoint called with payload: %s", request.dict())

    # Initialize arbiter and provider selector
    arbiter = InferenceArbiter()
    selector = InferenceProviderSelector(arbiter)

    try:
        logging_utility.info(
            "Selecting provider with provider=%s and model=%s",
            request.provider.value, request.model
        )
        provider_instance = selector.select_provider(
            provider=request.provider.value,
            model=request.model
        )
        logging_utility.info("Provider selected successfully: %s", provider_instance)
    except ValueError as ve:
        logging_utility.error("Provider selection error: %s", str(ve), exc_info=True)
        raise HTTPException(status_code=400, detail=str(ve))

    def stream_chunks():
        idx = 0
        logging_utility.info("Starting to stream chunks for thread_id=%s", request.thread_id)

        # Initial stabilization sequence
        yield "data: " + json.dumps({"status": "handshake"}) + "\n\n"
        yield "data: " + json.dumps({"status": "initializing"}) + "\n\n"

        try:
            chunk_generator = provider_instance.process_conversation(
                thread_id=request.thread_id,
                message_id=request.message_id,
                run_id=request.run_id,
                assistant_id=request.assistant_id,
                model=request.model,
                stream_reasoning=False
            )

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

                    # Normal chunk processing
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

                    # Ensure minimum structure
                    if "content" not in chunk_data:
                        chunk_data["content"] = ""

                    # Mark first meaningful chunk
                    if not first_chunk_sent and chunk_data.get("content"):
                        first_chunk_sent = True
                        chunk_data["first_chunk"] = True

                    yield "data: " + json.dumps(chunk_data) + "\n\n"

                except Exception as inner_exc:
                    logging_utility.error("Chunk processing error: %s", str(inner_exc))
                    yield "data: " + json.dumps({
                        "error": "chunk_processing_failed",
                        "message": str(inner_exc)
                    }) + "\n\n"

        except Exception as e:
            logging_utility.error("Stream generator error: %s", str(e))
            yield "data: " + json.dumps({
                "error": "stream_failure",
                "message": str(e)
            }) + "\n\n"
        finally:
            logging_utility.info("Stream completed for thread_id=%s", request.thread_id)
            yield "data: [DONE]\n\n"

    try:
        return StreamingResponse(
            stream_chunks(),
            media_type="text/event-stream",
            headers={
                "X-Stream-Init": "true",
                "Cache-Control": "no-cache, no-transform"
            }
        )
    except Exception as e:
        logging_utility.error("Stream setup failed: %s", str(e))
        raise HTTPException(status_code=500, detail="Stream initialization failed")