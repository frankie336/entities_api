from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from projectdavid_common import ValidationInterface
from projectdavid_common.utilities.logging_service import LoggingUtility
from sqlalchemy.orm import Session

from entities_api.dependencies import get_api_key, get_db
from entities_api.models.models import ApiKey as ApiKeyModel
from entities_api.services.message_service import MessageService

router = APIRouter()
logging_utility = LoggingUtility()


@router.post("/messages", response_model=ValidationInterface.MessageRead)
def create_message(
    message: ValidationInterface.MessageCreate,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(
        f"[{auth_key.user_id}] Creating a new message in thread ID: {message.thread_id}"
    )
    message_service = MessageService(db)
    try:
        new_message = message_service.create_message(message)
        logging_utility.info(f"Message created successfully with ID: {new_message.id}")
        return new_message
    except HTTPException as e:
        logging_utility.error(f"HTTP error during message creation: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"Unexpected error creating message: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.post("/messages/tools", response_model=ValidationInterface.MessageRead)
async def submit_tool_response(
    message: ValidationInterface.MessageCreate,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(
        f"[{auth_key.user_id}] Submitting tool output to thread ID: {message.thread_id}"
    )
    message_data = message.dict()
    message_data.setdefault("sender_id", None)
    message_service = MessageService(db)
    try:
        new_message = message_service.submit_tool_output(
            ValidationInterface.MessageCreate(**message_data)
        )
        logging_utility.info(
            f"Tool message created successfully with ID: {new_message.id}"
        )
        return new_message
    except HTTPException as e:
        logging_utility.error(f"HTTP error during tool message: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"Unexpected error during tool message: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.get("/messages/{message_id}", response_model=ValidationInterface.MessageRead)
def get_message(
    message_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(f"[{auth_key.user_id}] Retrieving message ID: {message_id}")
    message_service = MessageService(db)
    try:
        return message_service.retrieve_message(message_id)
    except HTTPException as e:
        logging_utility.error(f"HTTP error retrieving message {message_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(
            f"Unexpected error retrieving message {message_id}: {str(e)}"
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.get(
    "/threads/{thread_id}/messages",
    response_model=List[ValidationInterface.MessageRead],
)
def list_messages(
    thread_id: str,
    limit: int = 20,
    order: str = "asc",
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(
        f"[{auth_key.user_id}] Listing messages for thread: {thread_id}"
    )
    message_service = MessageService(db)
    try:
        return message_service.list_messages(
            thread_id=thread_id, limit=limit, order=order
        )
    except HTTPException as e:
        logging_utility.error(f"HTTP error listing messages: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"Unexpected error listing messages: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.get(
    "/threads/{thread_id}/formatted_messages", response_model=List[Dict[str, Any]]
)
def get_formatted_messages(
    thread_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(
        f"[{auth_key.user_id}] Getting formatted messages for thread: {thread_id}"
    )
    message_service = MessageService(db)
    try:
        return message_service.list_messages_for_thread(thread_id)
    except HTTPException as e:
        logging_utility.error(f"HTTP error getting formatted messages: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"Unexpected error getting formatted messages: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.post("/messages/assistant", response_model=ValidationInterface.MessageRead)
def save_assistant_message(
    message: ValidationInterface.MessageCreate,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(
        f"[{auth_key.user_id}] Received assistant message chunk for thread {message.thread_id}"
    )
    message_service = MessageService(db)
    try:
        new_message = message_service.save_assistant_message_chunk(
            thread_id=message.thread_id,
            content=message.content,
            role=message.role,
            assistant_id=message.assistant_id,
            sender_id=message.sender_id,
            is_last_chunk=message.is_last_chunk,
        )
        if new_message is None:
            logging_utility.debug("Non-final chunk received, no message returned yet.")
            raise HTTPException(
                status_code=500,
                detail="Message saving incomplete: awaiting final chunk.",
            )
        return new_message
    except HTTPException as e:
        logging_utility.error(f"HTTP error in assistant message: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"Unexpected error in assistant message: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
