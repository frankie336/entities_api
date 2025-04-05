import json
import time
from typing import List, Dict, Any

from entities_common import ValidationInterface, UtilsInterface
from fastapi import HTTPException
from sqlalchemy.orm import Session

from entities_api.models.models import Message, Thread
from entities_api.schemas.messages import MessageRead

validator = ValidationInterface()
from entities_api.services.logging_service import LoggingUtility

# Initialize logging

logging_utility = LoggingUtility()



class MessageService:
    def __init__(self, db: Session):
        self.db = db
        self.message_chunks: Dict[str, List[str]] = {}  # Temporary storage for message chunks
        logging_utility.info(f"Initialized MessageService with database session. Source: {__file__}")

    def create_message(self, message: validator.MessageCreate) -> validator.MessageRead:
        """
        Create a new message in the database.
        """
        logging_utility.info(f"Creating message for thread_id={message.thread_id}, role={message.role}. Source: {__file__}")

        # Check if thread exists
        db_thread = self.db.query(Thread).filter(Thread.id == message.thread_id).first()
        if not db_thread:
            logging_utility.error(f"Thread not found: {message.thread_id}. Source: {__file__}")
            raise HTTPException(status_code=404, detail="Thread not found")


        # Create the message
        db_message = Message(
            id=UtilsInterface.IdentifierService.generate_message_id(),
            assistant_id=message.assistant_id,  # Include assistant_id
            attachments=[],
            completed_at=None,
            content=message.content,
            created_at=int(time.time()),
            incomplete_at=None,
            incomplete_details=None,
            meta_data=json.dumps(message.meta_data),
            object="message",
            role=message.role,
            run_id=None,
            status=None,
            thread_id=message.thread_id,
            sender_id=message.sender_id
        )

        try:
            self.db.add(db_message)
            self.db.commit()
            self.db.refresh(db_message)
            logging_utility.info(f"Message created successfully: id={db_message.id}. Source: {__file__}")
        except Exception as e:
            self.db.rollback()
            logging_utility.error(f"Error creating message: {str(e)}. Source: {__file__}")
            raise HTTPException(status_code=500, detail="Failed to create message")

        return MessageRead(
            id=db_message.id,
            assistant_id=db_message.assistant_id,
            attachments=db_message.attachments,
            completed_at=db_message.completed_at,
            content=db_message.content,
            created_at=db_message.created_at,
            incomplete_at=db_message.incomplete_at,
            incomplete_details=db_message.incomplete_details,
            meta_data=json.loads(db_message.meta_data),
            object=db_message.object,
            role=db_message.role,
            run_id=db_message.run_id,
            status=db_message.status,
            thread_id=db_message.thread_id,
            sender_id=db_message.sender_id
        )

    def retrieve_message(self, message_id: str) -> MessageRead:
        """
        Retrieve a message by its ID.
        """
        logging_utility.info(f"Retrieving message with id={message_id}. Source: {__file__}")

        db_message = self.db.query(Message).filter(Message.id == message_id).first()
        if not db_message:
            logging_utility.error(f"Message not found: {message_id}. Source: {__file__}")
            raise HTTPException(status_code=404, detail="Message not found")

        logging_utility.info(f"Message retrieved successfully: id={db_message.id}. Source: {__file__}")
        return MessageRead(
            id=db_message.id,
            assistant_id=db_message.assistant_id,
            attachments=db_message.attachments,
            completed_at=db_message.completed_at,
            content=db_message.content,
            created_at=db_message.created_at,
            incomplete_at=db_message.incomplete_at,
            incomplete_details=db_message.incomplete_details,
            meta_data=json.loads(db_message.meta_data),
            object=db_message.object,
            role=db_message.role,
            run_id=db_message.run_id,
            status=db_message.status,
            thread_id=db_message.thread_id,
            sender_id=db_message.sender_id
        )

    def list_messages(self, thread_id: str, limit: int = 20, order: str = "asc") -> List[MessageRead]:
        """
        List messages for a thread, ordered by creation time.
        """
        logging_utility.info(f"Listing messages for thread_id={thread_id}, limit={limit}, order={order}. Source: {__file__}")

        db_thread = self.db.query(Thread).filter(Thread.id == thread_id).first()
        if not db_thread:
            logging_utility.error(f"Thread not found: {thread_id}. Source: {__file__}")
            raise HTTPException(status_code=404, detail="Thread not found")

        query = self.db.query(Message).filter(Message.thread_id == thread_id)
        if order == "asc":
            query = query.order_by(Message.created_at.asc())
        else:
            query = query.order_by(Message.created_at.desc())

        db_messages = query.limit(limit).all()
        logging_utility.info(f"Retrieved {len(db_messages)} messages for thread_id={thread_id}. Source: {__file__}")

        return [
            MessageRead(
                id=db_message.id,
                assistant_id=db_message.assistant_id,
                attachments=db_message.attachments,
                completed_at=db_message.completed_at,
                content=db_message.content,
                created_at=db_message.created_at,
                incomplete_at=db_message.incomplete_at,
                incomplete_details=db_message.incomplete_details,
                meta_data=json.loads(db_message.meta_data),
                object=db_message.object,
                role=db_message.role,
                run_id=db_message.run_id,
                status=db_message.status,
                thread_id=db_message.thread_id,
                sender_id=db_message.sender_id
            )
            for db_message in db_messages
        ]

    def save_assistant_message_chunk(
            self,
            thread_id: str,
            content: str,
            role: str,
            assistant_id: str,
            sender_id: str,
            is_last_chunk: bool = False,
    ) -> MessageRead:
        """
        Save a message chunk from the assistant, with support for streaming and dynamic roles.
        Returns the saved message as a Pydantic object.
        """
        logging_utility.info(
            f"Saving assistant message chunk for thread_id={thread_id}, sender_id={sender_id}, assistant_id={assistant_id}, role={role}, is_last_chunk={is_last_chunk}."
        )

        # Accumulate message chunks
        if thread_id not in self.message_chunks:
            self.message_chunks[thread_id] = []

        self.message_chunks[thread_id].append(content)

        # Return early if this is not the last chunk
        if not is_last_chunk:
            logging_utility.debug(f"Chunk saved for thread_id={thread_id}. Waiting for more chunks.")
            return None  # Return None or a placeholder if not the last chunk

        # Combine chunks into a complete message
        complete_message = ''.join(self.message_chunks[thread_id])
        del self.message_chunks[thread_id]



        # Create and save the message
        db_message = Message(
            id=UtilsInterface.IdentifierService.generate_message_id(),
            assistant_id=assistant_id,
            attachments=[],
            completed_at=int(time.time()),
            content=complete_message,
            created_at=int(time.time()),
            incomplete_at=None,
            incomplete_details=None,
            meta_data=json.dumps({}),
            object="message",
            role=role,
            run_id=None,
            tool_id=None,
            status=None,
            thread_id=thread_id,
            sender_id=sender_id
        )

        try:
            self.db.add(db_message)
            self.db.commit()
            self.db.refresh(db_message)  # Refresh to get the updated object
            logging_utility.info(f"Message saved successfully: id={db_message.id}.")
        except Exception as e:
            self.db.rollback()
            logging_utility.error(f"Error saving message: {str(e)}.")
            raise HTTPException(status_code=500, detail="Failed to save message")

        # Return the saved message as a Pydantic object
        return MessageRead(
            id=db_message.id,
            assistant_id=db_message.assistant_id,
            attachments=db_message.attachments,
            completed_at=db_message.completed_at,
            content=db_message.content,
            created_at=db_message.created_at,
            incomplete_at=db_message.incomplete_at,
            incomplete_details=db_message.incomplete_details,
            meta_data=json.loads(db_message.meta_data),
            object=db_message.object,
            role=db_message.role,
            run_id=db_message.run_id,
            status=db_message.status,
            thread_id=db_message.thread_id,
            sender_id=db_message.sender_id
        )

    def list_messages_for_thread(self, thread_id: str) -> List[Dict[str, Any]]:
        """
        List messages for a thread in a formatted structure.
        """
        logging_utility.info(f"Listing formatted messages for thread_id={thread_id}. Source: {__file__}")

        db_thread = self.db.query(Thread).filter(Thread.id == thread_id).first()
        if not db_thread:
            logging_utility.error(f"Thread not found: {thread_id}. Source: {__file__}")
            raise HTTPException(status_code=404, detail="Thread not found")

        db_messages = self.db.query(Message).filter(Message.thread_id == thread_id).order_by(
            Message.created_at.asc()).all()

        formatted_messages = [
            {
                "role": "system",
                "content": "Be as kind, intelligent, and helpful"
            }
        ]

        for db_message in db_messages:
            if db_message.role == "tool" and db_message.tool_id:
                formatted_messages.append({
                    "role": "tool",
                    "tool_call_id": db_message.tool_id,
                    "content": db_message.content
                })
            else:
                formatted_messages.append({
                    "role": db_message.role,
                    "content": db_message.content
                })

        logging_utility.info(
            f"Retrieved {len(formatted_messages)} formatted messages for thread_id={thread_id}. Source: {__file__}")
        return formatted_messages

    def submit_tool_output(self, message: validator.MessageCreate) -> MessageRead:
        """
        Create a new message in the database.
        """
        logging_utility.info(f"Creating message for thread_id={message.thread_id}, role={message.role}. Source: {__file__}")

        # Check if thread exists
        db_thread = self.db.query(Thread).filter(Thread.id == message.thread_id).first()
        if not db_thread:
            logging_utility.error(f"Thread not found: {message.thread_id}. Source: {__file__}")
            raise HTTPException(status_code=404, detail="Thread not found")


        # Create the message
        db_message = Message(
            id=UtilsInterface.IdentifierService.generate_message_id(),
            assistant_id=message.assistant_id,  # Include assistant_id
            attachments=[],
            completed_at=None,
            content=message.content,
            created_at=int(time.time()),
            incomplete_at=None,
            incomplete_details=None,
            meta_data=json.dumps(message.meta_data),
            object="message",
            role="tool",
            run_id=None,
            tool_id=message.tool_id,
            status=None,
            thread_id=message.thread_id,
            sender_id=message.sender_id,  # Allow sender_id to be None
        )

        try:
            self.db.add(db_message)
            self.db.commit()
            self.db.refresh(db_message)
            logging_utility.info(f"Message created successfully: id={db_message.id}. Source: {__file__}")
        except Exception as e:
            self.db.rollback()
            logging_utility.error(f"Error creating message: {str(e)}. Source: {__file__}")
            raise HTTPException(status_code=500, detail="Failed to create message")

        return MessageRead(
            id=db_message.id,
            assistant_id=db_message.assistant_id,
            attachments=db_message.attachments,
            completed_at=db_message.completed_at,
            content=db_message.content,
            created_at=db_message.created_at,
            incomplete_at=db_message.incomplete_at,
            incomplete_details=db_message.incomplete_details,
            meta_data=json.loads(db_message.meta_data),
            object=db_message.object,
            role=db_message.role,
            run_id=db_message.run_id,
            tool_id=db_message.tool_id,
            status=db_message.status,
            thread_id=db_message.thread_id,
        )
