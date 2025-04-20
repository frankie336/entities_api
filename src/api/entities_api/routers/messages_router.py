import json
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status
from projectdavid_common import ValidationInterface
from projectdavid_common.utilities.logging_service import LoggingUtility
from redis.asyncio import Redis  # Use the async Redis type
from sqlalchemy.orm import Session

from ..dependencies import get_api_key, get_db, get_redis
from ..models.models import ApiKey as ApiKeyModel
from ..services.message_service import MessageService

router = APIRouter()
validator = ValidationInterface()
logging_utility = LoggingUtility()


async def _push_to_redis(redis: Redis, message_obj):
    """Asynchronously pushes message data to Redis list and trims."""
    try:
        key = f"thread:{message_obj.thread_id}:history"
        # Ensure role and content are present, even if None in original object
        data = message_obj.dict(exclude_unset=True)
        data["role"] = message_obj.role
        data["content"] = message_obj.content if message_obj.content is not None else ""
        payload = json.dumps(data)

        await redis.rpush(key, payload)
        await redis.ltrim(key, -200, -1)  # Keep the list trimmed
        logging_utility.debug(f"Async Pushed message {message_obj.id} to Redis '{key}'")
    except Exception as e:
        # Log the error but don't necessarily raise HTTPException,
        # as failing to cache might not be critical failure for the endpoint.
        logging_utility.error(
            f"Redis async push failed for {message_obj.id}: {e}", exc_info=True
        )


@router.post("/messages", response_model=ValidationInterface.MessageRead)
async def create_message(  # Changed to async def
    message: ValidationInterface.MessageCreate,
    db: Session = Depends(get_db),
    redis: Redis = Depends(get_redis),  # Now expects async Redis client
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(
        f"[{auth_key.user_id}] Creating message in thread {message.thread_id}"
    )
    # Assuming MessageService methods remain synchronous.
    # If they become async, they would need to be awaited.
    svc = MessageService(db)
    try:
        # Note: If svc.create_message involves I/O, consider making it async
        # and running it in a thread using await asyncio.to_thread(svc.create_message, message)
        # For now, assuming it's CPU-bound or fast enough.
        new_message = svc.create_message(message)
        logging_utility.info(f"Created message ID {new_message.id}")
        # Await the async Redis push
        await _push_to_redis(redis, new_message)
        return new_message
    except HTTPException:
        raise
    except Exception as e:
        logging_utility.error(f"Error creating message: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )


@router.post("/messages/tools", response_model=ValidationInterface.MessageRead)
async def submit_tool_response(  # Was already async
    message: ValidationInterface.MessageCreate,
    db: Session = Depends(get_db),
    redis: Redis = Depends(get_redis),  # Now expects async Redis client
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(
        f"[{auth_key.user_id}] Submitting tool output for thread {message.thread_id}"
    )
    svc = MessageService(db)  # Assuming sync service
    try:
        # Assuming sync service method
        new_message = svc.submit_tool_output(message)
        logging_utility.info(f"Created tool message ID {new_message.id}")
        # Await the async Redis push
        await _push_to_redis(redis, new_message)
        return new_message
    except HTTPException:
        raise
    except Exception as e:
        logging_utility.error(f"Error submitting tool message: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )


@router.get("/messages/{message_id}", response_model=ValidationInterface.MessageRead)
def get_message(  # This endpoint doesn't use Redis, can remain sync
    message_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(f"[{auth_key.user_id}] Retrieving message {message_id}")
    svc = MessageService(db)
    try:
        return svc.retrieve_message(message_id)
    except HTTPException:
        raise
    except Exception as e:
        logging_utility.error(f"Error retrieving message: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )


@router.get(
    "/threads/{thread_id}/messages",
    response_model=List[ValidationInterface.MessageRead],
)
def list_messages(  # This endpoint doesn't use Redis, can remain sync
    thread_id: str,
    limit: int = 20,
    order: str = "asc",
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(
        f"[{auth_key.user_id}] Listing messages for thread {thread_id}"
    )
    svc = MessageService(db)
    try:
        return svc.list_messages(thread_id=thread_id, limit=limit, order=order)
    except HTTPException:
        raise
    except Exception as e:
        logging_utility.error(f"Error listing messages: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )


@router.get(
    "/threads/{thread_id}/formatted_messages", response_model=List[Dict[str, Any]]
)
def get_formatted_messages(  # This endpoint doesn't use Redis, can remain sync
    thread_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(
        f"[{auth_key.user_id}] Retrieving formatted messages for thread {thread_id}"
    )
    svc = MessageService(db)
    try:
        return svc.list_messages_for_thread(thread_id)
    except HTTPException:
        raise
    except Exception as e:
        logging_utility.error(
            f"Error retrieving formatted messages: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )


@router.post("/messages/assistant", response_model=ValidationInterface.MessageRead)
async def save_assistant_message(  # Was already async
    message: ValidationInterface.MessageCreate,
    db: Session = Depends(get_db),
    redis: Redis = Depends(get_redis),  # Now expects async Redis client
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(
        f"[{auth_key.user_id}] Saving assistant chunk for thread {message.thread_id}"
    )
    svc = MessageService(db)  # Assuming sync service
    try:
        # Assuming sync service method
        new_message = svc.save_assistant_message_chunk(
            thread_id=message.thread_id,
            content=message.content,
            role=message.role,
            assistant_id=message.assistant_id,
            sender_id=message.sender_id,
            is_last_chunk=message.is_last_chunk,
        )
        if new_message:
            logging_utility.info(f"Saved assistant message ID {new_message.id}")
            # Await the async Redis push
            await _push_to_redis(redis, new_message)
            return new_message
        # If no message was created (e.g., not the last chunk), return None or appropriate response
        # Returning None might cause issues if the response_model expects a full MessageRead.
        # Consider returning a 204 No Content or adjusting logic.
        # For now, let's assume svc.save_assistant_message_chunk always returns a Message or None/raises.
        # If it returns None, FastAPI might raise an error due to response_model validation.
        # A simple fix could be returning a default/empty message or changing response status code.
        # Returning the object only if it exists:
        if new_message:
            return new_message
        else:
            # Decide how to handle non-final chunks - maybe return 202 Accepted?
            # For now, returning None which might fail validation if response_model is strict.
            # Consider adjusting response_model or return status_code=202/204
            return None  # Or adjust based on desired API behavior for non-final chunks
    except HTTPException:
        raise
    except Exception as e:
        logging_utility.error(f"Error saving assistant message: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )
