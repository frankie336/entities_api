from typing import List, Optional, Dict, Any
from fastapi import HTTPException
from sqlalchemy.orm import Session
from models.models import Message, Thread, User
from api.v1.schemas import MessageCreate, MessageRead
from services.identifier_service import IdentifierService
import json
import time
import logging

# Initialize logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MessageService:
    def __init__(self, db: Session):
        self.db = db
        self.message_chunks: Dict[str, List[str]] = {}  # Temporary storage for message chunks

    def create_message(self, message: MessageCreate) -> MessageRead:
        # Check if thread exists
        db_thread = self.db.query(Thread).filter(Thread.id == message.thread_id).first()
        if not db_thread:
            raise HTTPException(status_code=404, detail="Thread not found")

        # Check if sender exists
        db_user = self.db.query(User).filter(User.id == message.sender_id).first()
        if not db_user:
            raise HTTPException(status_code=404, detail="Sender not found")

        db_message = Message(
            id=IdentifierService.generate_message_id(),
            assistant_id=None,
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

        self.db.add(db_message)
        self.db.commit()
        self.db.refresh(db_message)

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
        db_message = self.db.query(Message).filter(Message.id == message_id).first()
        if not db_message:
            raise HTTPException(status_code=404, detail="Message not found")

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
        db_thread = self.db.query(Thread).filter(Thread.id == thread_id).first()
        if not db_thread:
            raise HTTPException(status_code=404, detail="Thread not found")

        query = self.db.query(Message).filter(Message.thread_id == thread_id)
        if order == "asc":
            query = query.order_by(Message.created_at.asc())
        else:
            query = query.order_by(Message.created_at.desc())

        db_messages = query.limit(limit).all()
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

    def save_assistant_message_chunk(self, thread_id: str, content: str, is_last_chunk: bool = False) -> Optional[MessageRead]:
        if thread_id not in self.message_chunks:
            self.message_chunks[thread_id] = []

        self.message_chunks[thread_id].append(content)

        if not is_last_chunk:
            return None

        complete_message = ''.join(self.message_chunks[thread_id])
        del self.message_chunks[thread_id]

        db_thread = self.db.query(Thread).filter(Thread.id == thread_id).first()
        if not db_thread:
            raise HTTPException(status_code=404, detail="Thread not found")

        assistant_id = "assistant_id"  # Set a proper assistant ID
        sender_id = "assistant"  # Set a fixed sender ID for the assistant

        db_message = Message(
            id=IdentifierService.generate_message_id(),
            assistant_id=assistant_id,
            attachments=[],
            completed_at=int(time.time()),
            content=complete_message,
            created_at=int(time.time()),
            incomplete_at=None,
            incomplete_details=None,
            meta_data=json.dumps({}),
            object="message",
            role="assistant",
            run_id=None,
            status=None,
            thread_id=thread_id,
            sender_id=sender_id
        )

        self.db.add(db_message)
        self.db.commit()
        self.db.refresh(db_message)

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
        db_thread = self.db.query(Thread).filter(Thread.id == thread_id).first()
        if not db_thread:
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
            formatted_messages.append({
                "role": db_message.role,
                "content": db_message.content
            })

        return formatted_messages