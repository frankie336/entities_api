import json
import time
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from projectdavid_common import UtilsInterface, ValidationInterface
from sqlalchemy.orm import Session

# --- FIX: Step 1 ---
# Import the SessionLocal factory.
from src.api.entities_api.db.database import SessionLocal
from src.api.entities_api.models.models import Message, Thread
from src.api.entities_api.services.logging_service import LoggingUtility

validator = ValidationInterface()
logging_utility = LoggingUtility()


class MessageService:

    # --- FIX: Step 2 ---
    # The constructor no longer accepts or stores a database session.
    # The in-memory message_chunks cache is instance-specific and can remain.
    def __init__(self):
        self.message_chunks: Dict[str, List[str]] = {}
        logging_utility.info(f"Initialized MessageService. Source: {__file__}")

    def create_message(self, message: validator.MessageCreate) -> validator.MessageRead:
        """
        Create a new message in the database.
        """
        logging_utility.info(
            f"Creating message for thread_id={message.thread_id}, role={message.role}. Source: {__file__}"
        )
        # --- FIX: Step 3 ---
        # Each method now creates and manages its own session.
        with SessionLocal() as db:
            db_thread = db.query(Thread).filter(Thread.id == message.thread_id).first()
            if not db_thread:
                raise HTTPException(status_code=404, detail="Thread not found")

            db_message = Message(
                id=UtilsInterface.IdentifierService.generate_message_id(),
                assistant_id=message.assistant_id,
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
                sender_id=message.sender_id,
            )
            try:
                db.add(db_message)
                db.commit()
                db.refresh(db_message)
                logging_utility.info(
                    f"Message created successfully: id={db_message.id}. Source: {__file__}"
                )
            except Exception as e:
                db.rollback()
                raise HTTPException(status_code=500, detail="Failed to create message")

            return ValidationInterface.MessageRead(
                id=db_message.id,
                assistant_id=db_message.assistant_id,
                attachments=db_message.attachments,
                completed_at=db_message.completed_at,
                content=db_message.content,
                created_at=db_message.created_at,
                incomplete_at=db_message.incomplete_at,
                incomplete_details=db_message.incomplete_details,
                meta_data=json.loads(db_message.meta_data or "{}"),
                object=db_message.object,
                role=db_message.role,
                run_id=db_message.run_id,
                status=db_message.status,
                thread_id=db_message.thread_id,
                sender_id=db_message.sender_id,
            )

    def retrieve_message(self, message_id: str) -> ValidationInterface.MessageRead:
        """
        Retrieve a message by its ID.
        """
        logging_utility.info(
            f"Retrieving message with id={message_id}. Source: {__file__}"
        )
        with SessionLocal() as db:
            db_message = db.query(Message).filter(Message.id == message_id).first()
            if not db_message:
                raise HTTPException(status_code=404, detail="Message not found")

            return ValidationInterface.MessageRead(
                id=db_message.id,
                assistant_id=db_message.assistant_id,
                attachments=db_message.attachments,
                completed_at=db_message.completed_at,
                content=db_message.content,
                created_at=db_message.created_at,
                incomplete_at=db_message.incomplete_at,
                incomplete_details=db_message.incomplete_details,
                meta_data=json.loads(db_message.meta_data or "{}"),
                object=db_message.object,
                role=db_message.role,
                run_id=db_message.run_id,
                status=db_message.status,
                thread_id=db_message.thread_id,
                sender_id=db_message.sender_id,
            )

    def list_messages(
        self,
        thread_id: str,
        limit: int = 20,
        order: str = "asc",
    ) -> validator.MessagesList:
        """
        List messages for a thread, ordered by creation time.
        """
        logging_utility.info(
            f"Listing messages for thread_id={thread_id}, limit={limit}, "
            f"order={order}. Source: {__file__}"
        )
        with SessionLocal() as db:
            db_thread = db.query(Thread).filter(Thread.id == thread_id).first()
            if not db_thread:
                raise HTTPException(status_code=404, detail="Thread not found")

            query = db.query(Message).filter(Message.thread_id == thread_id)
            query = (
                query.order_by(Message.created_at.asc())
                if order == "asc"
                else query.order_by(Message.created_at.desc())
            )
            db_messages = query.limit(limit).all()

            messages: List[validator.MessageRead] = []
            for db_msg in db_messages:
                meta_data = db_msg.meta_data
                if isinstance(meta_data, str):
                    try:
                        meta_data = json.loads(meta_data)
                    except (TypeError, ValueError):
                        meta_data = {}
                messages.append(validator.MessageRead.model_validate(db_msg))

            return validator.MessagesList(
                data=messages,
                first_id=messages[0].id if messages else None,
                last_id=messages[-1].id if messages else None,
                has_more=len(db_messages) >= limit,
            )

    def save_assistant_message_chunk(
        self,
        thread_id: str,
        content: str,
        role: str,
        assistant_id: str,
        sender_id: str,
        is_last_chunk: bool = False,
    ) -> Optional[ValidationInterface.MessageRead]:
        """
        Save a message chunk from the assistant, with support for streaming.
        """
        if thread_id not in self.message_chunks:
            self.message_chunks[thread_id] = []
        self.message_chunks[thread_id].append(content)

        if not is_last_chunk:
            return None

        complete_message = "".join(self.message_chunks.pop(thread_id, []))

        with SessionLocal() as db:
            db_message = Message(
                id=UtilsInterface.IdentifierService.generate_message_id(),
                assistant_id=assistant_id,
                attachments=[],
                completed_at=int(time.time()),
                content=complete_message,
                created_at=int(time.time()),
                meta_data=json.dumps({}),
                object="message",
                role=role,
                thread_id=thread_id,
                sender_id=sender_id,
            )
            try:
                db.add(db_message)
                db.commit()
                db.refresh(db_message)
            except Exception as e:
                db.rollback()
                raise HTTPException(status_code=500, detail="Failed to save message")

            return ValidationInterface.MessageRead.model_validate(db_message)

    def list_messages_for_thread(self, thread_id: str) -> List[Dict[str, Any]]:
        """
        List messages for a thread in a formatted structure.
        """
        with SessionLocal() as db:
            db_thread = db.query(Thread).filter(Thread.id == thread_id).first()
            if not db_thread:
                raise HTTPException(status_code=404, detail="Thread not found")
            db_messages = (
                db.query(Message)
                .filter(Message.thread_id == thread_id)
                .order_by(Message.created_at.asc())
                .all()
            )
            formatted_messages = [
                {"role": "system", "content": "Be as kind, intelligent, and helpful"}
            ]
            for db_message in db_messages:
                if db_message.role == "tool" and db_message.tool_id:
                    formatted_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": db_message.tool_id,
                            "content": db_message.content,
                        }
                    )
                else:
                    formatted_messages.append(
                        {"role": db_message.role, "content": db_message.content}
                    )
            return formatted_messages

    def submit_tool_output(
        self, message: validator.MessageCreate
    ) -> ValidationInterface.MessageRead:
        """
        Create a new message in the database with role 'tool'.
        """
        with SessionLocal() as db:
            db_thread = db.query(Thread).filter(Thread.id == message.thread_id).first()
            if not db_thread:
                raise HTTPException(status_code=404, detail="Thread not found")
            db_message = Message(
                id=UtilsInterface.IdentifierService.generate_message_id(),
                assistant_id=message.assistant_id,
                content=message.content,
                created_at=int(time.time()),
                meta_data=json.dumps(message.meta_data),
                object="message",
                role="tool",
                tool_id=message.tool_id,
                thread_id=message.thread_id,
            )
            try:
                db.add(db_message)
                db.commit()
                db.refresh(db_message)
            except Exception as e:
                db.rollback()
                raise HTTPException(status_code=500, detail="Failed to create message")

            return ValidationInterface.MessageRead.model_validate(db_message)

    def delete_message(self, message_id: str) -> validator.MessageDeleted:
        """Delete message row and return deletion envelope."""
        with SessionLocal() as db:
            db_msg = db.query(Message).filter(Message.id == message_id).first()
            if not db_msg:
                raise HTTPException(status_code=404, detail="Message not found")
            db.delete(db_msg)
            db.commit()
            return validator.MessageDeleted(id=message_id)
