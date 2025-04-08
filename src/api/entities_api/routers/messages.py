from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from projectdavid_common import ValidationInterface
from sqlalchemy.orm import Session

from entities_api.dependencies import get_db
from entities_api.services.logging_service import LoggingUtility
from entities_api.services.message_service import MessageService

router = APIRouter()
logging_utility = LoggingUtility()


@router.post("/messages", response_model=ValidationInterface.MessageRead)
def create_message(
    message: ValidationInterface.MessageCreate, db: Session = Depends(get_db)
):
    logging_utility.info(
        f"Received request to create a new message in thread ID: {message.thread_id}"
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


@router.post("/messages/tools", response_model=ValidationInterface.MessageRead)
async def submit_tool_response(
    message: ValidationInterface.MessageCreate, db: Session = Depends(get_db)
):
    logging_utility.info(
        f"Received request to create a new message in thread ID: {message.thread_id}"
    )

    # Ensure sender_id is explicitly None if missing
    message_data = message.dict()
    if "sender_id" not in message_data or message_data["sender_id"] is None:
        message_data["sender_id"] = None  # Explicitly set None

    logging_utility.info(f"Final payload before saving: {message_data}")

    message_service = MessageService(db)
    try:
        new_message = message_service.submit_tool_output(
            ValidationInterface.MessageCreate(**message_data)
        )
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


@router.get("/messages/{message_id}", response_model=ValidationInterface.MessageRead)
def get_message(message_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to get message with ID: {message_id}")
    message_service = MessageService(db)
    try:
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


@router.get(
    "/threads/{thread_id}/messages",
    response_model=List[ValidationInterface.MessageRead],
)
def list_messages(
    thread_id: str, limit: int = 20, order: str = "asc", db: Session = Depends(get_db)
):
    logging_utility.info(
        f"Received request to list messages for thread ID: {thread_id}"
    )
    message_service = MessageService(db)
    try:
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


@router.get(
    "/threads/{thread_id}/formatted_messages", response_model=List[Dict[str, Any]]
)
def get_formatted_messages(thread_id: str, db: Session = Depends(get_db)):
    logging_utility.info(
        f"Received request to get formatted messages for thread ID: {thread_id}"
    )
    message_service = MessageService(db)
    try:
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


@router.post("/messages/assistant", response_model=ValidationInterface.MessageRead)
def save_assistant_message(
    message: ValidationInterface.MessageCreate, db: Session = Depends(get_db)
):
    logging_utility.info(
        "Received assistant message payload: %s. Source: %s",
        message.dict(),  # Log the entire payload
        __file__,
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
            logging_utility.debug(
                "Received non-final chunk. Returning early. Source: %s", __file__
            )
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
            message.dict(),
            __file__,
        )
        raise e

    except Exception as e:
        logging_utility.error(
            "Unexpected error processing message: %s. Payload: %s. Source: %s",
            str(e),
            message.dict(),
            __file__,
        )
        raise HTTPException(status_code=500, detail="Internal Server Error")
