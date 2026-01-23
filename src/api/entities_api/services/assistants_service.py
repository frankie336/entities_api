import time
from typing import Any, List

from fastapi import HTTPException
from projectdavid import Entity
from projectdavid_common import UtilsInterface, ValidationInterface
from sqlalchemy.orm import Session

# --- FIX: Step 1 ---
# Import the SessionLocal factory.
from src.api.entities_api.db.database import SessionLocal
from src.api.entities_api.models.models import (Assistant, Tool, User,
                                                VectorStore)
from src.api.entities_api.services.logging_service import LoggingUtility
from src.api.entities_api.utils.cache_utils import get_sync_invalidator

logging_utility = LoggingUtility()
validator = ValidationInterface()


# TODO We need a delete assistant method !
class AssistantService:
    """
    CRUD + relationship utilities for `Assistant`.
    """

    # ORM collections that require explicit handling
    RELATIONSHIP_FIELDS = {"tools", "users", "vector_stores"}

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

    # --- FIX: Step 3 ---
    # Helper methods that touch the database must now accept a session.
    def _resolve_tool_ids(self, raw: list[Any], db: Session) -> list[str]:
        """
        Accepts:
          • ["tool_abc", "tool_xyz"]
          • [{"id": "tool_abc"}, {"type": "web_search"}]
        Returns a list of tool IDs, creating a Tool row if only `type` is given.
        """
        ids: list[str] = []

        for item in raw or []:
            if isinstance(item, str):
                ids.append(item)
                continue

            if isinstance(item, dict) and "id" in item:
                ids.append(item["id"])
                continue

            if isinstance(item, dict) and "type" in item:
                tool_type = item["type"]
                tool = db.query(Tool).filter(Tool.type == tool_type).one_or_none()
                if not tool:
                    tool = Tool(
                        id=f"tool_{tool_type}",
                        name=tool_type.replace("_", " ").title(),
                        type=tool_type,
                    )
                    db.add(tool)
                    db.flush()  # assign PK
                ids.append(tool.id)

        return ids

    # ────────────────────────────────────────────────
    # Constructor
    # ────────────────────────────────────────────────
    # --- FIX: Step 2 ---
    # The constructor no longer accepts or stores a database session.
    def __init__(self):
        self.client = Entity()

    # ────────────────────────────────────────────────
    # CRUD
    # ────────────────────────────────────────────────
    def create_assistant(
        self, assistant: validator.AssistantCreate
    ) -> validator.AssistantRead:
        # --- FIX: Step 4 ---
        # Each method now creates and manages its own session.
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
                tool_configs=assistant.tools,
                tool_resources=assistant.tool_resources,
                meta_data=assistant.meta_data,
                top_p=assistant.top_p,
                temperature=assistant.temperature,
                response_format=assistant.response_format,
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
            logging_utility.debug(
                "Retrieved assistant %s | tool_configs=%s | tool_resources=%s",
                assistant_id,
                db_asst.tool_configs,
                db_asst.tool_resources,
            )
            return self.map_to_read_model(db_asst)

    def update_assistant(
        self,
        assistant_id: str,
        assistant_update: validator.AssistantUpdate,
    ) -> validator.AssistantRead:

        # ------------------------------------------
        # Invalidates current assistant cache!
        # ------------------------------------------
        try:
            cache = get_sync_invalidator()
            cache.invalidate_sync(assistant_id)
            logging_utility.info(f"Invalidated cache for assistant {assistant_id}")
        except Exception as e:
            # Don't fail the HTTP request just because Redis failed
            logging_utility.error(f"Failed to invalidate cache: {e}")

        with SessionLocal() as db:
            db_asst = db.query(Assistant).filter(Assistant.id == assistant_id).first()
            if not db_asst:
                raise HTTPException(404, "Assistant not found")

            data = assistant_update.model_dump(exclude_unset=True)

            for key, val in data.items():
                if key not in self.RELATIONSHIP_FIELDS:
                    setattr(db_asst, key, val)

            if "tools" in data:
                # Pass the session to the helper
                resolved_ids = self._resolve_tool_ids(data["tools"], db)
                new_tools = db.query(Tool).filter(Tool.id.in_(resolved_ids)).all()
                db_asst.tools = new_tools
                if all(isinstance(item, dict) for item in data["tools"]):
                    db_asst.tool_configs = data["tools"]
                else:
                    db_asst.tool_configs = [{"type": t.type} for t in new_tools]

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
                logging_utility.info(
                    "Assistant %s disassociated from user %s", assistant_id, user_id
                )
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
        # This method does not interact with the DB, so no changes are needed.
        data = db_asst.__dict__.copy()
        data.pop("_sa_instance_state", None)

        if db_asst.tool_configs:
            data["tools"] = db_asst.tool_configs
        else:
            data["tools"] = [{"id": t.id, "type": t.type} for t in db_asst.tools]

        return validator.AssistantRead.model_validate(data)
