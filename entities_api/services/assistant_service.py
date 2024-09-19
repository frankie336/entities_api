from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload
from models.models import Assistant, User
from entities_api.schemas import AssistantCreate, AssistantRead, AssistantUpdate
from entities_api.services.identifier_service import IdentifierService
import time


class AssistantService:
    def __init__(self, db: Session):
        self.db = db

    def create_assistant(self, assistant: AssistantCreate) -> AssistantRead:
        db_user = self.db.query(User).filter(User.id == assistant.user_id).first()
        if not db_user:
            raise HTTPException(status_code=404, detail="User not found")

        assistant_id = IdentifierService.generate_assistant_id()
        db_assistant = Assistant(
            id=assistant_id,
            user_id=assistant.user_id,
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