from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from projectdavid_common import ValidationInterface
from sqlalchemy.orm import Session

from src.api.entities_api.dependencies import get_api_key, get_db
from src.api.entities_api.models.models import ApiKey as ApiKeyModel
from src.api.entities_api.services.assistants_service import AssistantService
from src.api.entities_api.services.logging_service import LoggingUtility

router = APIRouter()
logging_utility = LoggingUtility()


@router.post("/assistants", response_model=ValidationInterface.AssistantRead)
def create_assistant(
    assistant: ValidationInterface.AssistantCreate,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    """
    Create a new assistant.

    Accepted payload fields:
    * `tools`           – legacy config list
    * `ptool_handlers`  – inline tool specs
    * `tool_resources`  – per-tool resource map (NEW)
    """
    logging_utility.info(
        "User '%s' – creating assistant id=%s",
        auth_key.user_id,
        assistant.id or "auto-generated",
    )
    service = AssistantService(db)
    try:
        return service.create_assistant(assistant)
    except HTTPException:
        raise
    except Exception as exc:
        logging_utility.error("Create assistant error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from exc


@router.get(
    "/assistants/{assistant_id}", response_model=ValidationInterface.AssistantRead
)
def get_assistant(
    assistant_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(
        "User '%s' – get assistant id=%s", auth_key.user_id, assistant_id
    )
    service = AssistantService(db)
    try:
        return service.retrieve_assistant(assistant_id)
    except HTTPException:
        raise
    except Exception as exc:
        logging_utility.error("Get assistant error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unexpected error"
        ) from exc


@router.put(
    "/assistants/{assistant_id}", response_model=ValidationInterface.AssistantRead
)
def update_assistant(
    assistant_id: str,
    assistant_update: ValidationInterface.AssistantUpdate,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    """
    Update any mutable assistant fields – including `tool_resources`.
    """
    logging_utility.info(
        "User '%s' – update assistant id=%s", auth_key.user_id, assistant_id
    )
    service = AssistantService(db)
    try:
        return service.update_assistant(assistant_id, assistant_update)
    except HTTPException:
        raise
    except Exception as exc:
        logging_utility.error("Update assistant error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unexpected error"
        ) from exc


@router.get("/assistants", response_model=list[ValidationInterface.AssistantRead])
def list_assistants(
    db: Session = Depends(get_db), auth_key: ApiKeyModel = Depends(get_api_key)
):
    """List assistants for the caller (derived from API-key)."""
    user_id = auth_key.user_id
    logging_utility.info("User %s – list assistants", user_id)
    service = AssistantService(db)
    return service.list_assistants_by_user(user_id)


@router.post("/users/{user_id}/assistants/{assistant_id}")
def associate_assistant_with_user(
    user_id: str,
    assistant_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(
        "User '%s' – associate assistant %s → user %s",
        auth_key.user_id,
        assistant_id,
        user_id,
    )
    service = AssistantService(db)
    try:
        service.associate_assistant_with_user(user_id, assistant_id)
        return {"message": "Assistant associated with user successfully"}
    except HTTPException:
        raise
    except Exception as exc:
        logging_utility.error("Associate assistant error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unexpected error"
        ) from exc


@router.delete("/users/{user_id}/assistants/{assistant_id}", status_code=204)
def disassociate_assistant_from_user(
    user_id: str,
    assistant_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(
        "User '%s' – disassociate assistant %s ← user %s",
        auth_key.user_id,
        assistant_id,
        user_id,
    )
    service = AssistantService(db)
    try:
        service.disassociate_assistant_from_user(user_id, assistant_id)
    except HTTPException:
        raise
    except Exception as exc:
        logging_utility.error("Disassociate assistant error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unexpected error"
        ) from exc
