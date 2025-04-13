# src/entities_api/routers/messages_router.py

from typing import Any, Dict, List

# --- Added Imports ---
from fastapi import Depends  # Added Depends, Query, status
from fastapi import APIRouter, HTTPException, Query, status
from projectdavid_common import ValidationInterface
from projectdavid_common.utilities.logging_service import LoggingUtility
from sqlalchemy.orm import Session

# --- Added Imports ---
from entities_api.dependencies import get_api_key, get_db
from entities_api.models.models import \
    ApiKey as ApiKeyModel  # Added ApiKeyModel
from entities_api.services.message_service import MessageService

router = APIRouter(
    # --- Added basic router config ---
    prefix="/messages",  # Group under /messages
    tags=["Messages"],
    responses={
        # Added standard responses including 401
        404: {"description": "Not Found"},
        401: {"description": "Authentication required"},
    },
)
logging_utility = LoggingUtility()


@router.post(
    "",  # Path relative to prefix -> POST /messages
    response_model=ValidationInterface.MessageRead,
    status_code=status.HTTP_201_CREATED,  # Added status code
)
def create_message(
    message: ValidationInterface.MessageCreate,
    db: Session = Depends(get_db),
    # --- Added API Key Dependency ---
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    # --- Updated Log ---
    logging_utility.info(
        f"Authenticated request from user {auth_key.user_id} to create message in thread ID: {message.thread_id}"
    )
    message_service = MessageService(db)
    try:
        new_message = message_service.create_message(message)
        logging_utility.info(f"Message created successfully with ID: {new_message.id}")
        return new_message
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while creating message: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(
            f"An unexpected error occurred while creating message: {str(e)}"
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


# Note: This endpoint was already async
@router.post(
    "/tools",  # Path relative to prefix -> POST /messages/tools
    response_model=ValidationInterface.MessageRead,
    status_code=status.HTTP_201_CREATED,  # Added status code
)
async def submit_tool_response(
    message: ValidationInterface.MessageCreate,
    db: Session = Depends(get_db),
    # --- Added API Key Dependency ---
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    # --- Updated Log ---
    logging_utility.info(
        f"Authenticated request from user {auth_key.user_id} to submit tool response in thread ID: {message.thread_id}"
    )

    # Existing logic remains
    # Ensure sender_id is explicitly None if missing
    message_data = message.model_dump()  # Pydantic v2+
    # message_data = message.dict() # Pydantic v1
    if "sender_id" not in message_data or message_data["sender_id"] is None:
        message_data["sender_id"] = None  # Explicitly set None

    logging_utility.info(f"Final payload before saving: {message_data}")

    message_service = MessageService(db)
    try:
        # Re-validate payload
        validated_payload = ValidationInterface.MessageCreate(**message_data)
        new_message = message_service.submit_tool_output(validated_payload)
        logging_utility.info(f"Message created successfully with ID: {new_message.id}")
        return new_message
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while creating message: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(
            f"An unexpected error occurred while creating message: {str(e)}"
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.get(
    "/{message_id}",  # Path relative to prefix -> GET /messages/{message_id}
    response_model=ValidationInterface.MessageRead,
)
def get_message(
    message_id: str,
    db: Session = Depends(get_db),
    # --- Added API Key Dependency ---
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    # --- Updated Log ---
    logging_utility.info(
        f"Authenticated request from user {auth_key.user_id} to get message with ID: {message_id}"
    )
    message_service = MessageService(db)
    try:
        # --- NOTE: NO AUTHORIZATION CHECK ADDED HERE ---
        message = message_service.retrieve_message(message_id)
        logging_utility.info(f"Message retrieved successfully with ID: {message_id}")
        return message
    except HTTPException as e:
        logging_utility.error(
            f"HTTP error occurred while retrieving message {message_id}: {str(e)}"
        )
        raise e
    except Exception as e:
        logging_utility.error(
            f"An unexpected error occurred while retrieving message {message_id}: {str(e)}"
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


# Changed path for consistency and added API key dep
@router.get(
    "/threads/{thread_id}",  # Path -> GET /messages/threads/{thread_id}
    response_model=List[ValidationInterface.MessageRead],
)
def list_messages(
    thread_id: str,
    limit: int = Query(20, ge=1, le=100),  # Added Query validation
    order: str = Query("desc", pattern="^(asc|desc)$"),  # Added Query validation
    db: Session = Depends(get_db),
    # --- Added API Key Dependency ---
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    # --- Updated Log ---
    logging_utility.info(
        f"Authenticated request from user {auth_key.user_id} to list messages for thread ID: {thread_id}"
    )
    message_service = MessageService(db)
    try:
        # --- NOTE: NO AUTHORIZATION CHECK ADDED HERE ---
        messages = message_service.list_messages(
            thread_id=thread_id, limit=limit, order=order
        )
        logging_utility.info(
            f"Successfully retrieved messages for thread ID: {thread_id}"
        )
        return messages
    except HTTPException as e:
        logging_utility.error(
            f"HTTP error occurred while listing messages for thread {thread_id}: {str(e)}"
        )
        raise e
    except Exception as e:
        logging_utility.error(
            f"An unexpected error occurred while listing messages for thread {thread_id}: {str(e)}"
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


# Changed path for consistency and added API key dep
@router.get(
    "/threads/{thread_id}/formatted",  # Path -> GET /messages/threads/{thread_id}/formatted
    response_model=List[Dict[str, Any]],
)
def get_formatted_messages(
    thread_id: str,
    db: Session = Depends(get_db),
    # --- Added API Key Dependency ---
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    # --- Updated Log ---
    logging_utility.info(
        f"Authenticated request from user {auth_key.user_id} to get formatted messages for thread ID: {thread_id}"
    )
    message_service = MessageService(db)
    try:
        # --- NOTE: NO AUTHORIZATION CHECK ADDED HERE ---
        messages = message_service.list_messages_for_thread(thread_id)
        logging_utility.info(
            f"Formatted messages retrieved successfully for thread ID: {thread_id}"
        )
        return messages
    except HTTPException as e:
        logging_utility.error(
            f"HTTP error occurred while retrieving formatted messages for thread {thread_id}: {str(e)}"
        )
        raise e
    except Exception as e:
        logging_utility.error(
            f"An unexpected error occurred while retrieving formatted messages for thread {thread_id}: {str(e)}"
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


# Added API key dep
@router.post(
    "/assistant",  # Path -> POST /messages/assistant
    response_model=ValidationInterface.MessageRead,
)
def save_assistant_message(
    message: ValidationInterface.MessageCreate,
    db: Session = Depends(get_db),
    # --- Added API Key Dependency ---
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    # --- Updated Log ---
    logging_utility.info(
        "Authenticated request from user %s to save assistant message. Payload: %s. Source: %s",
        auth_key.user_id,
        message.model_dump(),  # Pydantic v2+
        # message.dict(), # Pydantic v1
        __file__,
    )

    message_service = MessageService(db)
    try:
        # --- NOTE: NO AUTHORIZATION CHECK ADDED HERE ---
        # Get is_last_chunk safely
        is_last_chunk = getattr(message, "is_last_chunk", True)

        new_message = message_service.save_assistant_message_chunk(
            thread_id=message.thread_id,
            content=message.content,
            role=message.role,
            assistant_id=message.assistant_id,
            sender_id=message.sender_id,
            is_last_chunk=is_last_chunk,
        )

        # Existing chunk handling logic remains
        if new_message is None and is_last_chunk:
            logging_utility.error(
                f"Service returned None for the supposed last chunk in thread {message.thread_id}."
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to finalize message from chunks.",
            )
        elif new_message is None and not is_last_chunk:
            logging_utility.debug(
                "Received non-final chunk. Cannot return MessageRead. Consider changing endpoint response for chunks.",
                __file__,
            )
            # Returning 500 as original code did, but 202 might be better if client expects it
            raise HTTPException(
                status_code=500,
                detail="Message saving failed: No complete message to return (expected for non-final chunks).",
            )

        logging_utility.info("Message saved successfully. Message ID: %s. Source: %s")

        return new_message

    except HTTPException as e:
        logging_utility.error(
            "HTTP error processing message: %s. Payload: %s. Source: %s",
            str(e),
            message.model_dump(),  # Pydantic v2+
            # message.dict(), # Pydantic v1
            __file__,
        )
        raise e

    except Exception as e:
        logging_utility.error(
            "Unexpected error processing message: %s. Payload: %s. Source: %s",
            str(e),
            message.model_dump(),  # Pydantic v2+
            # message.dict(), # Pydantic v1
            __file__,
        )
        raise HTTPException(status_code=500, detail="Internal Server Error")
