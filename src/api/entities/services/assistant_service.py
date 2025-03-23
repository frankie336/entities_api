from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload
from entities.models.models import Assistant, User, Tool
from entities.schemas.schemas import AssistantCreate, AssistantRead, AssistantUpdate
from entities.services.logging_service import LoggingUtility
from entities.services.identifier_service import IdentifierService
from typing import List, Optional
import time

logging_utility = LoggingUtility()


class AssistantService:
    def __init__(self, db: Session):
        self.db = db

    def create_assistant(self, assistant: AssistantCreate) -> AssistantRead:
        # Use provided ID or generate new
        assistant_id = assistant.id or IdentifierService.generate_assistant_id()

        # Validate ID uniqueness if provided
        if assistant.id:
            existing = self.db.query(Assistant).filter(Assistant.id == assistant_id).first()
            if existing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Assistant with ID '{assistant_id}' already exists"
                )

        # Initialize tools as an empty list if not provided
        tools = assistant.tools if hasattr(assistant, 'tools') else []

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
            response_format=assistant.response_format,
            tools=tools  # Set the tools JSON field
        )

        self.db.add(db_assistant)
        self.db.commit()
        self.db.refresh(db_assistant)

        return AssistantRead.model_validate(db_assistant)

    def retrieve_assistant(self, assistant_id: str) -> AssistantRead:
        db_assistant = self.db.query(Assistant).options(
            joinedload(Assistant.registered_tools),  # Changed from tools to registered_tools
            joinedload(Assistant.vector_stores)
        ).filter(Assistant.id == assistant_id).first()

        logging_utility.debug(f"Retrieved assistant: {db_assistant} with vector_stores: {db_assistant.vector_stores}")
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

        # The sync_registered_tools method will be automatically called due to the event listener
        self.db.commit()
        self.db.refresh(db_assistant)

        return AssistantRead.model_validate(db_assistant)

    def associate_tool_with_assistant(self, assistant_id: str, tool_id: str) -> None:
        """
        Manually associate a specific tool with an assistant by adding it to registered_tools.
        This is an alternative to the automatic sync_registered_tools method.
        """
        assistant = self.db.query(Assistant).filter(Assistant.id == assistant_id).first()
        tool = self.db.query(Tool).filter(Tool.id == tool_id).first()

        if not assistant:
            raise HTTPException(status_code=404, detail="Assistant not found")
        if not tool:
            raise HTTPException(status_code=404, detail="Tool not found")

        # Check if tool is already associated
        if tool not in assistant.registered_tools:
            assistant.registered_tools.append(tool)

            # Also add to the tools JSON array if not already present
            tool_type = tool.type
            tools_json = assistant.tools or []
            if not any(t.get('type') == tool_type for t in tools_json):
                # Create a tool definition based on the tool model
                tool_def = {
                    "type": tool.type,
                    "function": tool.function
                }
                tools_json.append(tool_def)
                assistant.tools = tools_json

            self.db.commit()
            logging_utility.info(f"Tool ID: {tool_id} associated with assistant ID: {assistant_id}")

    def disassociate_tool_from_assistant(self, assistant_id: str, tool_id: str) -> None:
        """
        Manually disassociate a specific tool from an assistant by removing it from registered_tools.
        Also updates the tools JSON array.
        """
        assistant = self.db.query(Assistant).filter(Assistant.id == assistant_id).first()
        tool = self.db.query(Tool).filter(Tool.id == tool_id).first()

        if not assistant:
            raise HTTPException(status_code=404, detail="Assistant not found")
        if not tool:
            raise HTTPException(status_code=404, detail="Tool not found")

        # Remove from registered_tools if present
        if tool in assistant.registered_tools:
            assistant.registered_tools.remove(tool)

            # Also remove from tools JSON array if present
            tool_type = tool.type
            tools_json = assistant.tools or []
            assistant.tools = [t for t in tools_json if t.get('type') != tool_type]

            self.db.commit()
            logging_utility.info(f"Tool ID: {tool_id} disassociated from assistant ID: {assistant_id}")
        else:
            raise HTTPException(status_code=400, detail="Tool not associated with the assistant")

    def list_tools_by_assistant(self, assistant_id: str) -> List[dict]:
        """
        List all tools associated with a given assistant.
        Returns both the registered tool objects and the tool definitions from the JSON array.
        """
        assistant = self.db.query(Assistant).options(
            joinedload(Assistant.registered_tools)
        ).filter(Assistant.id == assistant_id).first()

        if not assistant:
            raise HTTPException(status_code=404, detail="Assistant not found")

        # Return the tools JSON array which should be in sync with registered_tools
        return assistant.tools or []

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
            logging_utility.info(f"Assistant ID: {assistant_id} disassociated from user ID: {user_id}")
        else:
            raise HTTPException(status_code=400, detail="Assistant not associated with the user")

    def list_assistants_by_user(self, user_id: str) -> List[AssistantRead]:
        """List all assistants associated with a given user."""
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        return [AssistantRead.model_validate(assistant) for assistant in user.assistants]