import time
from typing import List
from entities_common import ValidationInterface, UtilsInterface
from fastapi import HTTPException
from sqlalchemy.orm import Session

from entities import Entities

from entities_api.models.models import Assistant, User
from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()

validator = ValidationInterface()


class AssistantService:
    def __init__(self, db: Session):
        self.db = db
        self.client = Entities()

    def create_assistant(self, assistant: validator.AssistantCreate) -> validator.AssistantRead:
        # Use provided ID or generate new
        assistant_id = assistant.id or UtilsInterface.IdentifierService.generate_assistant_id()

        # Validate ID uniqueness if provided
        if assistant.id:
            existing = self.db.query(Assistant).filter(Assistant.id == assistant_id).first()
            if existing:
                raise HTTPException(
                    status_code=400, detail=f"Assistant with ID '{assistant_id}' already exists"
                )

        # Map tools (from the Pydantic model) to tool_configs (for the DB)
        db_assistant = Assistant(
            id=assistant_id,
            object="assistant",
            created_at=int(time.time()),
            name=assistant.name,
            description=assistant.description,
            model=assistant.model,
            instructions=assistant.instructions,
            tool_configs=assistant.tools,  # Store under tool_configs in the DB
            meta_data=assistant.meta_data,
            top_p=assistant.top_p,
            temperature=assistant.temperature,
            response_format=assistant.response_format,
        )

        self.db.add(db_assistant)
        self.db.commit()
        self.db.refresh(db_assistant)

        return self.map_to_read_model(db_assistant)

    def retrieve_assistant(self, assistant_id: str) -> validator.AssistantRead:
        db_assistant = self.db.query(Assistant).filter(Assistant.id == assistant_id).first()

        if not db_assistant:
            raise HTTPException(status_code=404, detail="Assistant not found")

        logging_utility.debug(
            f"Retrieved assistant: {db_assistant} with tool_configs: {db_assistant.tool_configs}"
        )

        # Use the updated mapping helper that correctly renames tool_configs to tools.
        return self.map_to_read_model(db_assistant)

    def update_assistant(
        self, assistant_id: str, assistant_update: validator.AssistantUpdate
    ) -> validator.AssistantRead:
        db_assistant = self.db.query(Assistant).filter(Assistant.id == assistant_id).first()
        if not db_assistant:
            raise HTTPException(status_code=404, detail="Assistant not found")

        update_data = assistant_update.model_dump(exclude_unset=True)

        # Update the database assistant instance with new data
        for key, value in update_data.items():
            setattr(db_assistant, key, value)

        self.db.commit()
        self.db.refresh(db_assistant)

        return self.map_to_read_model(db_assistant)

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
            logging_utility.info(
                f"Assistant ID: {assistant_id} disassociated from user ID: {user_id}"
            )
        else:
            raise HTTPException(status_code=400, detail="Assistant not associated with the user")

    def list_assistants_by_user(self, user_id: str) -> List[validator.AssistantRead]:
        """List all assistants associated with a given user."""
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        return [self.map_to_read_model(assistant) for assistant in user.assistants]

    def map_to_read_model(self, db_assistant: Assistant) -> validator.AssistantRead:
        """
        Helper method to map the database Assistant model to an AssistantRead model.
        This function ensures that the 'tool_configs' field from the DB is moved to the
        'tools' field as expected by the AssistantRead schema.
        """
        # Get a dict copy of the SQLAlchemy model.
        assistant_data = db_assistant.__dict__.copy()
        # Remove any SQLAlchemy internal attribute.
        assistant_data.pop("_sa_instance_state", None)
        # Rename the key from 'tool_configs' to 'tools'.
        assistant_data["tools"] = assistant_data.pop("tool_configs", None)
        return validator.AssistantRead.model_validate(assistant_data)
