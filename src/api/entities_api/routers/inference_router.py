import json
import os
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from projectdavid_common import ValidationInterface
from projectdavid_common.utilities.logging_service import LoggingUtility
from redis import Redis
from sqlalchemy.orm import Session

from src.api.entities_api.db.database import get_db
from src.api.entities_api.dependencies import get_redis
from src.api.entities_api.models.models import ApiKey
from src.api.entities_api.orchestration.engine.inference_arbiter import \
    InferenceArbiter
from src.api.entities_api.orchestration.engine.inference_provider_selector import \
    InferenceProviderSelector
from src.api.entities_api.services.assistants_service import AssistantService

router = APIRouter()
logging_utility = LoggingUtility()


async def get_api_key_flexible(
    request: Request,
    db: Session = Depends(get_db),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> ApiKey:
    """
    Backwards-compatible auth dependency for the completions endpoint.

    Accepts EITHER:
      - X-API-Key: <token>               (standard platform style)
      - Authorization: Bearer <token>    (legacy inference client style)

    Both resolve against the same api_keys table — no special cases.
    """
    token: Optional[str] = None

    if x_api_key:
        token = x_api_key
        logging_utility.debug("[AUTH] Using X-API-Key header")
    elif authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:]
        logging_utility.debug("[AUTH] Using Authorization: Bearer header (legacy)")

    if not token:
        logging_utility.warning("[AUTH] Rejected: No API key in any recognised header")
        raise HTTPException(
            status_code=401,
            detail="Missing API Key. Provide 'X-API-Key' or 'Authorization: Bearer <token>' header.",
        )

    logging_utility.debug(
        "[AUTH] Token received: prefix=%s length=%d",
        token[:8],
        len(token),
    )

    prefix = token[:8]
    if len(token) <= len(prefix):
        raise HTTPException(status_code=401, detail="Invalid API Key format.")

    from src.api.entities_api.models.models import ApiKey as ApiKeyModel

    key = (
        db.query(ApiKeyModel)
        .filter(
            ApiKeyModel.prefix == prefix,
            ApiKeyModel.is_active.is_(True),
        )
        .first()
    )

    logging_utility.debug("[AUTH] DB lookup: prefix=%s found=%s", prefix, key is not None)

    if not key or not key.verify_key(token):
        raise HTTPException(status_code=401, detail="Invalid or inactive API Key.")

    if key.expires_at and key.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="API Key has expired.")

    logging_utility.debug("[AUTH] Accepted: user_id=%s prefix=%s", key.user_id, prefix)
    return key


@router.post(
    "/completions",
    summary="Asynchronous completions streaming endpoint (Unified Orchestration)",
    response_description="A stream of JSON-formatted completions chunks",
)
async def completions(
    stream_request: ValidationInterface.StreamRequest,
    redis: Redis = Depends(get_redis),
    auth_key: ApiKey = Depends(get_api_key_flexible),
):
    logging_utility.info(
        "Completions endpoint called for model: %s, run: %s",
        stream_request.model,
        stream_request.run_id,
    )

    # --- ASSISTANT ACCESS GUARD ---
    try:
        asst_svc = AssistantService()
        assistant = asst_svc.retrieve_assistant(stream_request.assistant_id)
    except Exception as e:
        logging_utility.error(f"Assistant lookup failed: {e}", exc_info=True)
        raise HTTPException(status_code=404, detail="Assistant not found")

    is_owner = assistant.owner_id == auth_key.user_id
    is_shared = any(u.id == auth_key.user_id for u in getattr(assistant, "users", []))

    if not is_owner and not is_shared:
        logging_utility.warning(
            "Access denied: user %s attempted inference against assistant %s",
            auth_key.user_id,
            stream_request.assistant_id,
        )
        raise HTTPException(status_code=403, detail="You do not have access to this assistant")

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
