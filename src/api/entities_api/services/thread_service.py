from entities_common import ValidationInterface, UtilsInterface
from fastapi import HTTPException
from sqlalchemy.orm import Session

from entities_api.models.models import Thread, User, Message
from entities_api.schemas.users import UserBase

validator = ValidationInterface()


import json
import time
from typing import List, Dict, Any
from entities_api.services.logging_service import LoggingUtility

logging_utility= LoggingUtility()

class ThreadService:
    def __init__(self, db: Session):
        self.db = db

    def create_thread(self, thread: validator.ThreadCreate) -> validator.ThreadReadDetailed:
        existing_users = self.db.query(User).filter(User.id.in_(thread.participant_ids)).all()
        if len(existing_users) != len(thread.participant_ids):
            raise HTTPException(status_code=400, detail="Invalid user IDs")

        db_thread = Thread(
            id=UtilsInterface.IdentifierService.generate_thread_id(),
            created_at=int(time.time()),
            meta_data=json.dumps({}),
            object="thread",
            tool_resources=json.dumps({})
        )
        self.db.add(db_thread)

        for user in existing_users:
            db_thread.participants.append(user)

        self.db.commit()
        self.db.refresh(db_thread)

        return self._create_thread_read_detailed(db_thread)

    def get_thread(self, thread_id: str) -> validator.ThreadReadDetailed:
        db_thread = self._get_thread_or_404(thread_id)
        return self._create_thread_read_detailed(db_thread)


    def delete_thread(self, thread_id: str) -> bool:
        db_thread = self._get_thread_or_404(thread_id)
        self.db.query(Message).filter(Message.thread_id == thread_id).delete()
        db_thread.participants = []
        self.db.delete(db_thread)
        self.db.commit()

        return True

    def list_threads_by_user(self, user_id: str) -> List[str]:
        threads = self.db.query(Thread).join(Thread.participants).filter(User.id == user_id).all()
        return [thread.id for thread in threads]

    def update_thread_metadata(self, thread_id: str, new_metadata: Dict[str, Any]) -> validator.ThreadReadDetailed:
        db_thread = self._get_thread_or_404(thread_id)
        db_thread.meta_data = json.dumps(new_metadata)
        self.db.commit()
        self.db.refresh(db_thread)
        return self._create_thread_read_detailed(db_thread)

    def update_thread(self, thread_id: str, thread_update: validator.ThreadUpdate) -> validator.ThreadReadDetailed:
        logging_utility.info(f"Attempting to update thread with id: {thread_id}")
        logging_utility.info(f"Update data: {thread_update.dict()}")
        db_thread = self._get_thread_or_404(thread_id)
        update_data = thread_update.dict(exclude_unset=True)

        if 'meta_data' in update_data:
            current_metadata = json.loads(db_thread.meta_data)
            current_metadata.update(update_data['meta_data'])
            db_thread.meta_data = json.dumps(current_metadata)

        for key, value in update_data.items():
            if key != 'meta_data':
                setattr(db_thread, key, value)

        self.db.commit()
        self.db.refresh(db_thread)
        logging_utility.info(f"Successfully updated thread with id: {thread_id}")
        return self._create_thread_read_detailed(db_thread)

    def _get_thread_or_404(self, thread_id: str) -> Thread:
        db_thread = self.db.query(Thread).filter(Thread.id == thread_id).first()
        if not db_thread:
            raise HTTPException(status_code=404, detail="Thread not found")
        return db_thread

    def _create_thread_read_detailed(self, db_thread: Thread) -> validator.ThreadReadDetailed:
        participants = [UserBase.from_orm(user) for user in db_thread.participants]
        return validator.ThreadReadDetailed(
            id=db_thread.id,
            created_at=db_thread.created_at,
            meta_data=json.loads(db_thread.meta_data),
            object=db_thread.object,
            tool_resources=json.loads(db_thread.tool_resources),
            participants=participants
        )