# entities_api/routers/assistants_router.py
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from projectdavid.clients.users_client import UsersClient
from projectdavid_common import ValidationInterface
from sqlalchemy.orm import Session

from entities_api.dependencies import get_api_key, get_db
from entities_api.models.models import ApiKey as ApiKeyModel
from entities_api.services.assistants_service import AssistantService
from entities_api.services.logging_service import LoggingUtility

router = APIRouter()
logging_utility = LoggingUtility()


# ------------------------------------------------------------------ #
#  CREATE
# ------------------------------------------------------------------ #
@router.post("/assistants", response_model=ValidationInterface.AssistantRead)
def create_assistant(
    assistant: ValidationInterface.AssistantCreate,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    """
    Create an assistant.

    `assistant.platform_tools` is accepted automatically via the
    `AssistantCreate` schema.  The service layer persists it in the
    dedicated `platform_tools` column; legacy `tools` mapping is
    untouched.
    """
    logging_utility.info(
        "User '%s' – creating assistant id=%s",
        auth_key.user_id,
        assistant.id or "auto-generated",
    )
    service = AssistantService(db)
    try:
        return service.create_assistant(assistant)
    except Exception as exc:
        logging_utility.error("Create assistant error: %s", exc, exc_info=True)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from exc


# ------------------------------------------------------------------ #
#  RETRIEVE
# ------------------------------------------------------------------ #
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
    except Exception as exc:
        logging_utility.error("Get assistant error: %s", exc, exc_info=True)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error",
        ) from exc


# ------------------------------------------------------------------ #
#  UPDATE
# ------------------------------------------------------------------ #
@router.put(
    "/assistants/{assistant_id}", response_model=ValidationInterface.AssistantRead
)
def update_assistant(
    assistant_id: str,
    assistant_update: ValidationInterface.AssistantUpdate,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(
        "User '%s' – update assistant id=%s", auth_key.user_id, assistant_id
    )
    service = AssistantService(db)
    try:
        return service.update_assistant(assistant_id, assistant_update)
    except Exception as exc:
        logging_utility.error("Update assistant error: %s", exc, exc_info=True)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error",
        ) from exc


# ------------------------------------------------------------------ #
#  LIST-BY-USER
# ------------------------------------------------------------------ #
@router.get(
    "/users/{user_id}/assistants",
    response_model=List[ValidationInterface.AssistantRead],
)
def list_assistants_by_user(
    user_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.info(
        "User '%s' – list assistants for user %s", auth_key.user_id, user_id
    )
    user_client = UsersClient(db)
    try:
        return user_client.list_assistants_by_user(user_id)
    except Exception as exc:
        logging_utility.error("List assistants error: %s", exc, exc_info=True)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error",
        ) from exc


# ------------------------------------------------------------------ #
#  ASSOCIATE
# ------------------------------------------------------------------ #
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
    except Exception as exc:
        logging_utility.error("Associate assistant error: %s", exc, exc_info=True)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error",
        ) from exc


# ------------------------------------------------------------------ #
#  DISASSOCIATE
# ------------------------------------------------------------------ #
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
        return {"message": "Assistant disassociated from user successfully"}
    except Exception as exc:
        logging_utility.error("Disassociate assistant error: %s", exc, exc_info=True)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error",
        ) from exc
