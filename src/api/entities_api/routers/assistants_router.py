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


@router.post("/assistants", response_model=ValidationInterface.AssistantRead)
def create_assistant(
    assistant: ValidationInterface.AssistantCreate,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):

    logging_utility.info(
        f"User '{auth_key.user_id}' - Creating assistant with ID: {assistant.id or 'auto-generated'}"
    )
    assistant_service = AssistantService(db)
    try:
        new_assistant = assistant_service.create_assistant(assistant)
        return new_assistant
    except HTTPException as e:
        raise
    except Exception as e:
        logging_utility.error(f"User '{auth_key.user_id}' - Unexpected error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get(
    "/assistants/{assistant_id}", response_model=ValidationInterface.AssistantRead
)
def get_assistant(
    assistant_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    logging_utility.error(
        f"!!!!!! ASSISTANTS GET ENDPOINT REACHED for {assistant_id} by user {auth_key.user_id} !!!!!!"
    )  # ADD THIS

    logging_utility.info(
        f"User '{auth_key.user_id}' - Received request to get assistant with ID: {assistant_id}"
    )
    assistant_service = AssistantService(db)
    try:
        assistant = assistant_service.retrieve_assistant(assistant_id)
        logging_utility.info(
            f"User '{auth_key.user_id}' - Assistant retrieved successfully with ID: {assistant_id}"
        )
        return assistant
    except HTTPException as e:
        logging_utility.error(
            f"User '{auth_key.user_id}' - HTTP error occurred while retrieving assistant {assistant_id}: {str(e)}"
        )
        raise e
    except Exception as e:
        logging_utility.error(
            f"User '{auth_key.user_id}' - An unexpected error occurred while retrieving assistant {assistant_id}: {str(e)}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )


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
        f"User '{auth_key.user_id}' - Received request to update assistant with ID: {assistant_id}"
    )
    assistant_service = AssistantService(db)
    try:
        updated_assistant = assistant_service.update_assistant(
            assistant_id, assistant_update
        )
        logging_utility.info(
            f"User '{auth_key.user_id}' - Assistant updated successfully with ID: {assistant_id}"
        )
        return updated_assistant
    except HTTPException as e:
        logging_utility.error(
            f"User '{auth_key.user_id}' - HTTP error occurred while updating assistant {assistant_id}: {str(e)}"
        )
        raise e
    except Exception as e:
        logging_utility.error(
            f"User '{auth_key.user_id}' - An unexpected error occurred while updating assistant {assistant_id}: {str(e)}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )


@router.get(
    "/users/{user_id}/assistants",
    response_model=List[ValidationInterface.AssistantRead],
)
def list_assistants_by_user(
    user_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    """
    Endpoint to list all assistants associated with a given user.
    """
    logging_utility.info(
        f"User '{auth_key.user_id}' - Received request to list assistants for user ID: {user_id}"
    )
    user_service = UsersClient(db)
    try:
        assistants = user_service.list_assistants_by_user(user_id)
        logging_utility.info(
            f"User '{auth_key.user_id}' - Assistants retrieved for user ID: {user_id}"
        )
        return assistants
    except HTTPException as e:
        logging_utility.error(
            f"User '{auth_key.user_id}' - HTTP error occurred while listing assistants for user {user_id}: {str(e)}"
        )
        raise e
    except Exception as e:
        logging_utility.error(
            f"User '{auth_key.user_id}' - An unexpected error occurred while listing assistants for user {user_id}: {str(e)}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )


@router.post("/users/{user_id}/assistants/{assistant_id}")
def associate_assistant_with_user(
    user_id: str,
    assistant_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    """
    Endpoint to associate an assistant with a user.
    """
    logging_utility.info(
        f"User '{auth_key.user_id}' - Received request to associate assistant ID: {assistant_id} with user ID: {user_id}"
    )
    assistant_service = AssistantService(db)
    try:
        assistant_service.associate_assistant_with_user(user_id, assistant_id)
        logging_utility.info(
            f"User '{auth_key.user_id}' - Assistant ID: {assistant_id} associated successfully with user ID: {user_id}"
        )
        return {"message": "Assistant associated with user successfully"}
    except HTTPException as e:
        logging_utility.error(
            f"User '{auth_key.user_id}' - HTTP error occurred while associating assistant {assistant_id} with user {user_id}: {str(e)}"
        )
        raise e
    except Exception as e:
        logging_utility.error(
            f"User '{auth_key.user_id}' - An unexpected error occurred while associating assistant {assistant_id} with user {user_id}: {str(e)}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )


# entities_api/routers.py


@router.delete("/users/{user_id}/assistants/{assistant_id}", status_code=204)
def disassociate_assistant_from_user(
    user_id: str,
    assistant_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    """
    Endpoint to disassociate an assistant from a user.
    """
    logging_utility.info(
        f"User '{auth_key.user_id}' - Received request to disassociate assistant ID: {assistant_id} from user ID: {user_id}"
    )
    assistant_service = AssistantService(db)
    try:
        assistant_service.disassociate_assistant_from_user(user_id, assistant_id)
        logging_utility.info(
            f"User '{auth_key.user_id}' - Assistant ID: {assistant_id} disassociated successfully from user ID: {user_id}"
        )
        return {"message": "Assistant disassociated from user successfully"}
    except HTTPException as e:
        logging_utility.error(
            f"User '{auth_key.user_id}' - HTTP error occurred while disassociating assistant {assistant_id} from user {user_id}: {str(e)}"
        )
        raise e
    except Exception as e:
        logging_utility.error(
            f"User '{auth_key.user_id}' - An unexpected error occurred while disassociating assistant {assistant_id} from user {user_id}: {str(e)}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )
