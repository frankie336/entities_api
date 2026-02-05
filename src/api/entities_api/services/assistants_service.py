# src/api/entities_api/services/assistant_service.py
import time
from typing import Any, List

from fastapi import HTTPException
from projectdavid import Entity
from projectdavid_common import UtilsInterface, ValidationInterface

# --- FIX: Removed Tool from imports ---
from src.api.entities_api.db.database import SessionLocal
from src.api.entities_api.models.models import Assistant, User, VectorStore
from src.api.entities_api.services.logging_service import LoggingUtility
from src.api.entities_api.utils.cache_utils import get_sync_invalidator

logging_utility = LoggingUtility()
validator = ValidationInterface()


class AssistantService:
    """
    CRUD + relationship utilities for `Assistant`.
    """

    # Removed "tools" from relationship fields as it is now a JSON column (tool_configs)
    RELATIONSHIP_FIELDS = {"users", "vector_stores"}

    # ────────────────────────────────────────────────
    # Helpers
    # ────────────────────────────────────────────────
    @staticmethod
    def _extract_ids(raw_list: list[Any]) -> list[str]:
        """Return only string IDs; ignore items without an `id` field."""
        ids: list[str] = []
        for item in raw_list or []:
            if isinstance(item, str):
                ids.append(item)
            elif isinstance(item, dict) and "id" in item:
                ids.append(item["id"])
        return ids

    # --- FIX: Removed _resolve_tool_ids ---
    # We no longer create or resolve Tool rows in the database.

    # ────────────────────────────────────────────────
    # Constructor
    # ────────────────────────────────────────────────
    def __init__(self):
        self.client = Entity()

    # ────────────────────────────────────────────────
    # CRUD
    # ────────────────────────────────────────────────
    def create_assistant(
        self, assistant: validator.AssistantCreate
    ) -> validator.AssistantRead:
        with SessionLocal() as db:
            assistant_id = (
                assistant.id or UtilsInterface.IdentifierService.generate_assistant_id()
            )
            if assistant.id and (
                db.query(Assistant).filter(Assistant.id == assistant_id).first()
            ):
                raise HTTPException(
                    status_code=400,
                    detail=f"Assistant with ID '{assistant_id}' already exists",
                )

            db_assistant = Assistant(
                id=assistant_id,
                object="assistant",
                created_at=int(time.time()),
                name=assistant.name,
                description=assistant.description,
                model=assistant.model,
                instructions=assistant.instructions,
                # Mapping the 'tools' list from the schema to the JSON column
                tool_configs=assistant.tools,
                tool_resources=assistant.tool_resources,
                meta_data=assistant.meta_data,
                top_p=assistant.top_p,
                temperature=assistant.temperature,
                response_format=assistant.response_format,
                # --- New Agentic Fields ---
                max_turns=assistant.max_turns,
                agent_mode=assistant.agent_mode,
                decision_telemetry=assistant.decision_telemetry,
            )

            db.add(db_assistant)
            db.commit()
            db.refresh(db_assistant)
            return self.map_to_read_model(db_assistant)

    def retrieve_assistant(self, assistant_id: str) -> validator.AssistantRead:
        with SessionLocal() as db:
            db_asst = db.query(Assistant).filter(Assistant.id == assistant_id).first()
            if not db_asst:
                raise HTTPException(status_code=404, detail="Assistant not found")

            return self.map_to_read_model(db_asst)

    def update_assistant(
        self,
        assistant_id: str,
        assistant_update: validator.AssistantUpdate,
    ) -> validator.AssistantRead:

        try:
            cache = get_sync_invalidator()
            cache.invalidate_sync(assistant_id)
            logging_utility.info(f"Invalidated cache for assistant {assistant_id}")
        except Exception as e:
            logging_utility.error(f"Failed to invalidate cache: {e}")

        with SessionLocal() as db:
            db_asst = db.query(Assistant).filter(Assistant.id == assistant_id).first()
            if not db_asst:
                raise HTTPException(404, "Assistant not found")

            data = assistant_update.model_dump(exclude_unset=True)

            # Update basic fields (including tool_configs if passed directly)
            for key, val in data.items():
                if key not in self.RELATIONSHIP_FIELDS and key != "tools":
                    setattr(db_asst, key, val)

            # -------------------------------------------------------
            # TOOLS UPDATE (Handled as JSON blob)
            # -------------------------------------------------------
            if "tools" in data:
                # Replace or append logic for the JSON tool definitions
                incoming_tools = data["tools"]
                # If you want to replace tools entirely (standard OpenAI behavior):
                db_asst.tool_configs = incoming_tools

            if "users" in data:
                db_asst.users = (
                    db.query(User)
                    .filter(User.id.in_(self._extract_ids(data["users"])))
                    .all()
                )

            if "vector_stores" in data:
                db_asst.vector_stores = (
                    db.query(VectorStore)
                    .filter(
                        VectorStore.id.in_(self._extract_ids(data["vector_stores"]))
                    )
                    .all()
                )

            db.commit()
            db.refresh(db_asst)
            return self.map_to_read_model(db_asst)

    # ────────────────────────────────────────────────
    # User-assistant linking helpers
    # ────────────────────────────────────────────────
    def associate_assistant_with_user(self, user_id: str, assistant_id: str):
        with SessionLocal() as db:
            user = db.query(User).filter(User.id == user_id).first()
            assistant = db.query(Assistant).filter(Assistant.id == assistant_id).first()
            if not user:
                raise HTTPException(404, "User not found")
            if not assistant:
                raise HTTPException(404, "Assistant not found")
            user.assistants.append(assistant)
            db.commit()

    def disassociate_assistant_from_user(self, user_id: str, assistant_id: str):
        with SessionLocal() as db:
            user = db.query(User).filter(User.id == user_id).first()
            assistant = db.query(Assistant).filter(Assistant.id == assistant_id).first()
            if not user:
                raise HTTPException(404, "User not found")
            if not assistant:
                raise HTTPException(404, "Assistant not found")
            if assistant in user.assistants:
                user.assistants.remove(assistant)
                db.commit()
            else:
                raise HTTPException(400, "Assistant not associated with the user")

    def list_assistants_by_user(self, user_id: str) -> List[validator.AssistantRead]:
        with SessionLocal() as db:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise HTTPException(404, "User not found")
            return [self.map_to_read_model(a) for a in user.assistants]

    # ────────────────────────────────────────────────
    # Mapper
    # ────────────────────────────────────────────────
    def map_to_read_model(self, db_asst: Assistant) -> validator.AssistantRead:
        """
        Maps DB Assistant to Pydantic AssistantRead.
        Ensures the 'tools' field in schema is populated from 'tool_configs' JSON.
        """
        data = db_asst.__dict__.copy()
        data.pop("_sa_instance_state", None)

        # FIX: The source of truth is strictly the tool_configs JSON column
        data["tools"] = db_asst.tool_configs or []

        return validator.AssistantRead.model_validate(data)
