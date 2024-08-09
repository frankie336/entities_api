from fastapi import HTTPException
from sqlalchemy.orm import Session
from models.models import Thread, User, Message
from api.v1.schemas import ThreadCreate, ThreadReadDetailed, UserBase, MessageRead
from services.identifier_service import IdentifierService
import json
import time
from typing import List

class ThreadService:
    def __init__(self, db: Session):
        self.db = db

    def create_thread(self, thread: ThreadCreate) -> ThreadReadDetailed:
        # Check if all users exist
        existing_users = self.db.query(User).filter(User.id.in_(thread.participant_ids)).all()
        if len(existing_users) != len(thread.participant_ids):
            raise HTTPException(status_code=400, detail="Invalid user IDs")

        db_thread = Thread(
            id=IdentifierService.generate_thread_id(),
            created_at=int(time.time()),
            meta_data=json.dumps(thread.meta_data),  # Convert dict to JSON string
            object="thread",  # Set object_type
            tool_resources=json.dumps({})  # Initialize tool_resources as JSON string
        )
        self.db.add(db_thread)

        for user in existing_users:
            db_thread.participants.append(user)

        self.db.commit()
        self.db.refresh(db_thread)

        participants = [UserBase.from_orm(user) for user in db_thread.participants]

        return ThreadReadDetailed(
            id=db_thread.id,
            created_at=db_thread.created_at,
            meta_data=json.loads(db_thread.meta_data),  # Convert JSON string back to dict
            object=db_thread.object,
            tool_resources=json.loads(db_thread.tool_resources),  # Convert JSON string back to dict
            participants=participants  # Include participants in the response
        )

    def get_thread(self, thread_id: str) -> ThreadReadDetailed:
        db_thread = self.db.query(Thread).filter(Thread.id == thread_id).first()
        if not db_thread:
            raise HTTPException(status_code=404, detail="Thread not found")

        participants = [UserBase.from_orm(user) for user in db_thread.participants]

        return ThreadReadDetailed(
            id=db_thread.id,
            created_at=db_thread.created_at,
            meta_data=json.loads(db_thread.meta_data),  # Convert JSON string back to dict
            object=db_thread.object,
            tool_resources=json.loads(db_thread.tool_resources),  # Convert JSON string back to dict
            participants=participants  # Include participants in the response
        )

    def delete_thread(self, thread_id: str) -> None:
        db_thread = self.db.query(Thread).filter(Thread.id == thread_id).first()
        if not db_thread:
            raise HTTPException(status_code=404, detail="Thread not found")

        # Remove all messages associated with the thread
        self.db.query(Message).filter(Message.thread_id == thread_id).delete()

        # Remove relationships with participants
        db_thread.participants = []

        # Delete the thread itself
        self.db.delete(db_thread)
        self.db.commit()

    def list_threads_by_user(self, user_id: str) -> List[str]:
        threads = self.db.query(Thread).join(Thread.participants).filter(User.id == user_id).all()
        return [thread.id for thread in threads]
