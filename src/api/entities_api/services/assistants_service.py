import time
from typing import List

from fastapi import HTTPException
from projectdavid import Entity
from projectdavid_common import UtilsInterface, ValidationInterface
from sqlalchemy.orm import Session

from entities_api.models.models import Assistant, User
from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()
validator = ValidationInterface()


class AssistantService:
    def __init__(self, db: Session):
        self.db = db
        self.client = Entity()

    # ------------------------------------------------------------ #
    #  CREATE
    # ------------------------------------------------------------ #
    def create_assistant(
        self, assistant: validator.AssistantCreate
    ) -> validator.AssistantRead:
        assistant_id = (
            assistant.id or UtilsInterface.IdentifierService.generate_assistant_id()
        )

        # Guard against ID collision when caller supplies one
        if assistant.id and self.db.query(Assistant).filter(
            Assistant.id == assistant_id
        ).first():
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
            #
            # ─── Relationships represented as JSON blobs ───────────
            #
            tool_configs=assistant.tools,         # existing “classic” tools
            tool_resources=assistant.tool_resources,  # NEW ⬅
            platform_tools=assistant.platform_tools,  # inline spec list
            #
            meta_data=assistant.meta_data,
            top_p=assistant.top_p,
            temperature=assistant.temperature,
            response_format=assistant.response_format,
        )

        self.db.add(db_assistant)
        self.db.commit()
        self.db.refresh(db_assistant)
        return self.map_to_read_model(db_assistant)

    # ------------------------------------------------------------ #
    #  RETRIEVE
    # ------------------------------------------------------------ #
    def retrieve_assistant(self, assistant_id: str) -> validator.AssistantRead:
        db_asst = self.db.query(Assistant).filter(Assistant.id == assistant_id).first()
        if not db_asst:
            raise HTTPException(status_code=404, detail="Assistant not found")

        logging_utility.debug(
            f"Retrieved assistant {assistant_id} | "
            f"tool_configs={db_asst.tool_configs} | "
            f"tool_resources={db_asst.tool_resources} | "
            f"platform_tools={db_asst.platform_tools}"
        )
        return self.map_to_read_model(db_asst)

    # ------------------------------------------------------------ #
    #  UPDATE
    # ------------------------------------------------------------ #
    def update_assistant(
        self, assistant_id: str, assistant_update: validator.AssistantUpdate
    ) -> validator.AssistantRead:
        db_asst = self.db.query(Assistant).filter(Assistant.id == assistant_id).first()
        if not db_asst:
            raise HTTPException(status_code=404, detail="Assistant not found")

        # Only mutate provided fields (tool_resources included)
        for key, value in assistant_update.model_dump(exclude_unset=True).items():
            setattr(db_asst, key, value)

        self.db.commit()
        self.db.refresh(db_asst)
        return self.map_to_read_model(db_asst)

    # ------------------------------------------------------------ #
    #  USER ⟷ ASSISTANT LINKS
    # ------------------------------------------------------------ #
    def associate_assistant_with_user(self, user_id: str, assistant_id: str):
        user = self.db.query(User).filter(User.id == user_id).first()
        assistant = (
            self.db.query(Assistant).filter(Assistant.id == assistant_id).first()
        )

        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if not assistant:
            raise HTTPException(status_code=404, detail="Assistant not found")

        user.assistants.append(assistant)
        self.db.commit()

    def disassociate_assistant_from_user(self, user_id: str, assistant_id: str):
        user = self.db.query(User).filter(User.id == user_id).first()
        assistant = (
            self.db.query(Assistant).filter(Assistant.id == assistant_id).first()
        )

        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if not assistant:
            raise HTTPException(status_code=404, detail="Assistant not found")

        if assistant in user.assistants:
            user.assistants.remove(assistant)
            self.db.commit()
            logging_utility.info(
                f"Assistant {assistant_id} disassociated from user {user_id}"
            )
        else:
            raise HTTPException(
                status_code=400, detail="Assistant not associated with the user"
            )

    # ------------------------------------------------------------ #
    #  LIST
    # ------------------------------------------------------------ #
    def list_assistants_by_user(self, user_id: str) -> List[validator.AssistantRead]:
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        return [self.map_to_read_model(a) for a in user.assistants]

    # ------------------------------------------------------------ #
    #  HELPER
    # ------------------------------------------------------------ #
    def map_to_read_model(self, db_asst: Assistant) -> validator.AssistantRead:
        """
        Convert SQLAlchemy Assistant → Pydantic AssistantRead.
        """
        data = db_asst.__dict__.copy()
        data.pop("_sa_instance_state", None)

        # SQL column → Pydantic field name remaps
        data["tools"] = data.pop("tool_configs", None)
        # platform_tools and tool_resources pass straight through

        return validator.AssistantRead.model_validate(data)
