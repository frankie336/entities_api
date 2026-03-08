import json
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from projectdavid_common import ValidationInterface
from projectdavid_common.utilities.logging_service import LoggingUtility
from redis import Redis

from src.api.entities_api.dependencies import get_redis
from src.api.entities_api.orchestration.engine.inference_arbiter import \
    InferenceArbiter
from src.api.entities_api.orchestration.engine.inference_provider_selector import \
    InferenceProviderSelector
from src.api.entities_api.services.native_execution_service import \
    NativeExecutionService

router = APIRouter()
logging_utility = LoggingUtility()


@router.post(
    "/completions",
    summary="Asynchronous completions streaming endpoint (Unified Orchestration)",
    response_description="A stream of JSON-formatted completions chunks",
)
async def completions(
    stream_request: ValidationInterface.StreamRequest,
    redis: Redis = Depends(get_redis),
):
    logging_utility.info(
        "Completions endpoint called for model: %s, run: %s",
        stream_request.model,
        stream_request.run_id,
    )

    # ------------------------------------------------------------------
    # OWNERSHIP GUARD
    #
    # The run is the trust anchor. It was created under auth, so its
    # user_id is reliable. We verify that the thread and assistant IDs
    # in the request are consistent with the run — this closes the
    # mismatched-ID attack vector without requiring a second API key.
    #
    # ARCH NOTE: This endpoint requires two separate credentials:
    #   - stream_request.api_key → Inference provider key (forwarded to LLM)
    #   - Project David identity  → Derived from run.user_id (trust anchor)
    #
    # We cannot add get_api_key here without breaking the dual-key
    # constraint: the client cannot simultaneously pass a Project David
    # key in the header AND an inference provider key in the body through
    # the current SDK flow. Identity is therefore established via the run.
    #
    # Chain of trust:
    #   1. Run exists and was created under auth (run.user_id is trusted)
    #   2. run.thread_id matches the request (no thread grafting)
    #   3. run.assistant_id matches the request (no assistant grafting)
    #   4. Caller has owner/shared access to the assistant
    # ------------------------------------------------------------------
    try:
        native = NativeExecutionService()

        run = await native.retrieve_run(stream_request.run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found.")

        # ── Guard 1: run.thread_id matches the request ───────────────
        if run.thread_id != stream_request.thread_id:
            raise HTTPException(
                status_code=403,
                detail="Thread ID does not match the run.",
            )

        # ── Guard 2: run.assistant_id matches the request ────────────
        if run.assistant_id != stream_request.assistant_id:
            raise HTTPException(
                status_code=403,
                detail="Assistant ID does not match the run.",
            )

        # ── Guard 3: caller has access to the assistant ──────────────
        await native.assert_assistant_access(
            assistant_id=stream_request.assistant_id,
            user_id=run.user_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logging_utility.error(f"Ownership check failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Ownership verification failed.")

    # ------------------------------------------------------------------
    # PROVIDER SETUP
    # ------------------------------------------------------------------
    try:
        arbiter = InferenceArbiter(redis=redis)
        selector = InferenceProviderSelector(arbiter)
        general_handler_instance, api_model_name = selector.select_provider(
            model_id=stream_request.model
        )
    except Exception as e:
        logging_utility.error(f"Provider setup failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    # ------------------------------------------------------------------
    # STREAM
    # ------------------------------------------------------------------
    async def stream_generator():
        start_time = time.time()
        run_id = stream_request.run_id
        prefix = "data: "
        suffix = "\n\n"
        chunk_count = 0
        error_occurred = False

        try:
            async for chunk in general_handler_instance.process_conversation(
                thread_id=stream_request.thread_id,
                message_id=stream_request.message_id,
                run_id=run_id,
                assistant_id=stream_request.assistant_id,
                model=stream_request.model,
                stream_reasoning=False,
                api_key=stream_request.api_key,
            ):
                chunk_count += 1
                final_str = ""

                if isinstance(chunk, str):
                    final_str = chunk
                elif isinstance(chunk, dict):
                    if "run_id" not in chunk:
                        chunk["run_id"] = run_id
                    final_str = json.dumps(chunk)
                else:
                    final_str = json.dumps(
                        {"type": "content", "content": str(chunk), "run_id": run_id}
                    )

                yield f"{prefix}{final_str}{suffix}"

            if not error_occurred:
                yield "data: [DONE]\n\n"

        except Exception as e:
            error_occurred = True
            logging_utility.error(f"Stream loop error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'run_id': run_id, 'message': str(e)})}\n\n"
        finally:
            elapsed = time.time() - start_time
            logging_utility.info(f"Stream finished: {chunk_count} chunks in {elapsed:.2f}s")

    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream",
        },
    )
