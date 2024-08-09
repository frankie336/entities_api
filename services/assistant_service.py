from http.client import HTTPException
from sqlalchemy.orm import Session
from models.models import Assistant, User
from api.v1.schemas import AssistantCreate, AssistantRead, AssistantUpdate
from services.identifier_service import IdentifierService
import json
import time

class AssistantService:
    def __init__(self, db: Session):
        self.db = db

    def create_assistant(self, assistant: AssistantCreate) -> AssistantRead:
        # Check if the user exists
        db_user = self.db.query(User).filter(User.id == assistant.user_id).first()
        if not db_user:
            raise HTTPException(status=404, detail="User not found")

        assistant_id = IdentifierService.generate_assistant_id()
        tools_json = json.dumps([tool.dict(exclude_unset=True) for tool in assistant.tools])  # Convert list of Tool objects to JSON
        db_assistant = Assistant(
            id=assistant_id,
            user_id=assistant.user_id,
            object="assistant",  # Set the object field
            created_at=int(time.time()),
            name=assistant.name,
            description=assistant.description,
            model=assistant.model,
            instructions=assistant.instructions,
            tools=tools_json,  # Store JSON string
            meta_data=json.dumps(assistant.meta_data),  # Convert dict to JSON string
            top_p=assistant.top_p,
            temperature=assistant.temperature,
            response_format=assistant.response_format
        )
        self.db.add(db_assistant)
        self.db.commit()
        self.db.refresh(db_assistant)

        return AssistantRead.from_orm(self._convert_db_assistant(db_assistant))

    def get_assistant(self, assistant_id: str) -> AssistantRead:
        db_assistant = self.db.query(Assistant).filter(Assistant.id == assistant_id).first()
        if not db_assistant:
            raise HTTPException(status=404, detail="Assistant not found")
        return AssistantRead.from_orm(self._convert_db_assistant(db_assistant))

    def update_assistant(self, assistant_id: str, assistant_update: AssistantUpdate) -> AssistantRead:
        db_assistant = self.db.query(Assistant).filter(Assistant.id == assistant_id).first()
        if not db_assistant:
            raise HTTPException(status=404, detail="Assistant not found")

        update_data = assistant_update.dict(exclude_unset=True)
        if 'tools' in update_data:
            update_data['tools'] = json.dumps([tool.dict(exclude_unset=True) for tool in assistant_update.tools])
        if 'meta_data' in update_data:
            update_data['meta_data'] = json.dumps(assistant_update.meta_data)

        for key, value in update_data.items():
            setattr(db_assistant, key, value)

        self.db.commit()
        self.db.refresh(db_assistant)

        return AssistantRead.from_orm(self._convert_db_assistant(db_assistant))

    def _convert_db_assistant(self, db_assistant: Assistant) -> Assistant:
        """Convert JSON fields back to their original types."""
        db_assistant.tools = json.loads(db_assistant.tools)
        db_assistant.meta_data = json.loads(db_assistant.meta_data)
        return db_assistant
