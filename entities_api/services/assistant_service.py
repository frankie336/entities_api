from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload
from entities_api.models.models import Assistant, User
from entities_api.schemas import AssistantCreate, AssistantRead, AssistantUpdate
from entities_api.services.logging_service import LoggingUtility
from entities_api.services.identifier_service import IdentifierService
from typing import List
import time

logging_utility = LoggingUtility()

class AssistantService:
    def __init__(self, db: Session):
        self.db = db

    def create_assistant(self, assistant: AssistantCreate) -> AssistantRead:
        assistant_id = IdentifierService.generate_assistant_id()
        db_assistant = Assistant(
            id=assistant_id,
            object="assistant",
            created_at=int(time.time()),
            name=assistant.name,
            description=assistant.description,
            model=assistant.model,
            instructions=assistant.instructions,
            meta_data=assistant.meta_data,
            top_p=assistant.top_p,
            temperature=assistant.temperature,
            response_format=assistant.response_format
        )

        self.db.add(db_assistant)
        self.db.commit()
        self.db.refresh(db_assistant)

        return AssistantRead.model_validate(db_assistant)

    def get_assistant(self, assistant_id: str) -> AssistantRead:
        db_assistant = self.db.query(Assistant).options(
            joinedload(Assistant.tools)
        ).filter(Assistant.id == assistant_id).first()
        if not db_assistant:
            raise HTTPException(status_code=404, detail="Assistant not found")
        return AssistantRead.model_validate(db_assistant)

    def update_assistant(self, assistant_id: str, assistant_update: AssistantUpdate) -> AssistantRead:
        db_assistant = self.db.query(Assistant).filter(Assistant.id == assistant_id).first()
        if not db_assistant:
            raise HTTPException(status_code=404, detail="Assistant not found")

        update_data = assistant_update.model_dump(exclude_unset=True)

        for key, value in update_data.items():
            setattr(db_assistant, key, value)

        self.db.commit()
        self.db.refresh(db_assistant)

        return AssistantRead.model_validate(db_assistant)

    def associate_assistant_with_user(self, user_id: str, assistant_id: str):
        """Associate an assistant with a user (many-to-many relationship)."""
        user = self.db.query(User).filter(User.id == user_id).first()
        assistant = self.db.query(Assistant).filter(Assistant.id == assistant_id).first()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if not assistant:
            raise HTTPException(status_code=404, detail="Assistant not found")

        user.assistants.append(assistant)
        self.db.commit()

    # entities_api/services/assistant_service.py

    def disassociate_assistant_from_user(self, user_id: str, assistant_id: str):
        """Disassociate an assistant from a user (many-to-many relationship)."""
        user = self.db.query(User).filter(User.id == user_id).first()
        assistant = self.db.query(Assistant).filter(Assistant.id == assistant_id).first()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if not assistant:
            raise HTTPException(status_code=404, detail="Assistant not found")

        if assistant in user.assistants:
            user.assistants.remove(assistant)
            self.db.commit()
            logging_utility.info(f"Assistant ID: {assistant_id} disassociated from user ID: {user_id}")
        else:
            raise HTTPException(status_code=400, detail="Assistant not associated with the user")

    def list_assistants_by_user(self, user_id: str) -> List[AssistantRead]:  # Use List instead of list for compatibility
        """List all assistants associated with a given user."""
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        return [AssistantRead.model_validate(assistant) for assistant in user.assistants]
