import time
from typing import Any, List

from fastapi import HTTPException
from projectdavid import Entity
from projectdavid_common import UtilsInterface, ValidationInterface
from sqlalchemy.orm import Session

from src.api.entities_api.models.models import (Assistant, Tool, User,
                                                VectorStore)
from src.api.entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()
validator = ValidationInterface()


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

    def _resolve_tool_ids(self, raw: list[Any]) -> list[str]:
        """
        Accepts:
          • ["tool_abc", "tool_xyz"]
          • [{"id": "tool_abc"}, {"type": "web_search"}]
        Returns a list of tool IDs, creating a Tool row if only `type` is given.
        """
        ids: list[str] = []

        for item in raw or []:
            # Already a plain ID
            if isinstance(item, str):
                ids.append(item)
                continue

            # Dict with explicit ID
            if isinstance(item, dict) and "id" in item:
                ids.append(item["id"])
                continue

            # Dict keyed by "type" → look up or create
            if isinstance(item, dict) and "type" in item:
                tool_type = item["type"]
                tool = self.db.query(Tool).filter(Tool.type == tool_type).one_or_none()
                if not tool:
                    tool = Tool(
                        id=f"tool_{tool_type}",
                        name=tool_type.replace("_", " ").title(),
                        type=tool_type,
                    )
                    self.db.add(tool)
                    self.db.flush()  # assign PK
                ids.append(tool.id)

        return ids

    # ────────────────────────────────────────────────
    # Constructor
    # ────────────────────────────────────────────────
    def __init__(self, db: Session):
        self.db = db
        self.client = Entity()

    # ────────────────────────────────────────────────
    # CRUD
    # ────────────────────────────────────────────────
    def create_assistant(
        self, assistant: validator.AssistantCreate
    ) -> validator.AssistantRead:
        assistant_id = (
            assistant.id or UtilsInterface.IdentifierService.generate_assistant_id()
        )
        if assistant.id and (
            self.db.query(Assistant).filter(Assistant.id == assistant_id).first()
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

        self.db.add(db_assistant)
        self.db.commit()
        self.db.refresh(db_assistant)
        return self.map_to_read_model(db_assistant)

    def retrieve_assistant(self, assistant_id: str) -> validator.AssistantRead:
        db_asst = self.db.query(Assistant).filter(Assistant.id == assistant_id).first()
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
        # ── fetch ─────────────────────────────────────────────────────
        db_asst = self.db.query(Assistant).filter(Assistant.id == assistant_id).first()
        if not db_asst:
            raise HTTPException(404, "Assistant not found")

        data = assistant_update.model_dump(exclude_unset=True)

        # ── 1) scalar / JSON columns ──────────────────────────────────
        for key, val in data.items():
            if key not in self.RELATIONSHIP_FIELDS:
                setattr(db_asst, key, val)

        # ── 2) relationship collections ──────────────────────────────
        if "tools" in data:
            resolved_ids = self._resolve_tool_ids(data["tools"])
            new_tools = self.db.query(Tool).filter(Tool.id.in_(resolved_ids)).all()
            db_asst.tools = new_tools

            # ⭐ keep tool_configs JSON in sync with what caller sent
            if all(isinstance(item, dict) for item in data["tools"]):
                db_asst.tool_configs = data["tools"]  # caller sent dicts
            else:
                db_asst.tool_configs = [  # caller sent IDs
                    {"type": t.type} for t in new_tools
                ]

        if "users" in data:
            db_asst.users = (
                self.db.query(User)
                .filter(User.id.in_(self._extract_ids(data["users"])))
                .all()
            )

        if "vector_stores" in data:
            db_asst.vector_stores = (
                self.db.query(VectorStore)
                .filter(VectorStore.id.in_(self._extract_ids(data["vector_stores"])))
                .all()
            )

        # ── commit & return ──────────────────────────────────────────
        self.db.commit()
        self.db.refresh(db_asst)
        return self.map_to_read_model(db_asst)

    # ────────────────────────────────────────────────
    # User-assistant linking helpers
    # ────────────────────────────────────────────────
    def associate_assistant_with_user(self, user_id: str, assistant_id: str):
        user = self.db.query(User).filter(User.id == user_id).first()
        assistant = (
            self.db.query(Assistant).filter(Assistant.id == assistant_id).first()
        )
        if not user:
            raise HTTPException(404, "User not found")
        if not assistant:
            raise HTTPException(404, "Assistant not found")
        user.assistants.append(assistant)
        self.db.commit()

    def disassociate_assistant_from_user(self, user_id: str, assistant_id: str):
        user = self.db.query(User).filter(User.id == user_id).first()
        assistant = (
            self.db.query(Assistant).filter(Assistant.id == assistant_id).first()
        )
        if not user:
            raise HTTPException(404, "User not found")
        if not assistant:
            raise HTTPException(404, "Assistant not found")
        if assistant in user.assistants:
            user.assistants.remove(assistant)
            self.db.commit()
            logging_utility.info(
                "Assistant %s disassociated from user %s", assistant_id, user_id
            )
        else:
            raise HTTPException(400, "Assistant not associated with the user")

    def list_assistants_by_user(self, user_id: str) -> List[validator.AssistantRead]:
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(404, "User not found")
        return [self.map_to_read_model(a) for a in user.assistants]

    # ────────────────────────────────────────────────
    # Mapper
    # ────────────────────────────────────────────────
    def map_to_read_model(self, db_asst: Assistant) -> validator.AssistantRead:
        data = db_asst.__dict__.copy()
        data.pop("_sa_instance_state", None)

        # ⭐ new logic
        if db_asst.tool_configs:
            data["tools"] = db_asst.tool_configs  # use explicit configs
        else:
            data["tools"] = [{"id": t.id, "type": t.type} for t in db_asst.tools]

        return validator.AssistantRead.model_validate(data)
