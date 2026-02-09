# src/api/entities_api/routers/users_router.py
from fastapi import APIRouter, Depends, HTTPException, status
from projectdavid_common import ValidationInterface
from projectdavid_common.utilities.logging_service import LoggingUtility
from sqlalchemy.orm import Session

from src.api.entities_api.dependencies import get_api_key, get_db
from src.api.entities_api.models.models import ApiKey as ApiKeyModel
from src.api.entities_api.models.models import User as UserModel
from src.api.entities_api.serializers import UserUpdate
from src.api.entities_api.services.user_service import UserService

validation = ValidationInterface()
router = APIRouter(prefix="/users", tags=["Users"])
logging_utility = LoggingUtility()


@router.post(
    "", response_model=validation.UserRead, status_code=status.HTTP_201_CREATED
)
def create_user(
    user_data: validation.UserCreate,
    db: Session = Depends(get_db),  # Session is kept here for the admin check.
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    """
    Creates a new user. Requires **Admin** authentication via API Key.
    """
    logging_utility.info(f"User '{auth_key.user_id}' requesting to create a new user.")
    # Direct DB access for authorization check remains.
    requesting_admin = (
        db.query(UserModel).filter(UserModel.id == auth_key.user_id).first()
    )
    if not requesting_admin or not requesting_admin.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required to create users.",
        )

    # --- FIX APPLIED HERE ---
    user_service = UserService()
    try:
        new_user = user_service.create_user(user_data)
        logging_utility.info(
            f"User '{new_user.email}' (ID: {new_user.id}) created successfully by admin {requesting_admin.id}."
        )
        return new_user
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while creating the user.",
        )


@router.get("/{user_id}", response_model=validation.UserRead)
def get_user(
    user_id: str,
    db: Session = Depends(get_db),  # Session is kept here for the auth check.
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    """
    Retrieves details for a specific user.
    """
    logging_utility.info(
        f"User '{auth_key.user_id}' requesting details for user ID: {user_id}"
    )
    requesting_user = (
        db.query(UserModel).filter(UserModel.id == auth_key.user_id).first()
    )
    if not requesting_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )
    if not requesting_user.is_admin and requesting_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to access this user's details.",
        )

    # --- FIX APPLIED HERE ---
    user_service = UserService()
    try:
        user = user_service.get_user(user_id)
        return user
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.put("/{user_id}", response_model=validation.UserRead)
def update_user(
    user_id: str,
    user_update: UserUpdate,
    db: Session = Depends(get_db),  # Session is kept here for the auth check.
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    """
    Updates details for a specific user.
    """
    logging_utility.info(
        f"User '{auth_key.user_id}' requesting to update user ID: {user_id}"
    )
    requesting_user = (
        db.query(UserModel).filter(UserModel.id == auth_key.user_id).first()
    )
    if not requesting_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )
    is_admin_request = requesting_user.is_admin
    is_self_request = requesting_user.id == user_id
    if not is_admin_request and not is_self_request:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to update this user.",
        )
    update_data = user_update.model_dump(exclude_unset=True)
    if not is_admin_request and "is_admin" in update_data:
        del update_data["is_admin"]

    # --- FIX APPLIED HERE ---
    user_service = UserService()
    try:
        updated_user = user_service.update_user(user_id, UserUpdate(**update_data))
        return updated_user
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: str,
    db: Session = Depends(get_db),  # Session is kept here for the admin check.
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    """
    Deletes a specific user. Requires **Admin** authentication.
    """
    logging_utility.info(
        f"User '{auth_key.user_id}' requesting to delete user ID: {user_id}"
    )
    requesting_admin = (
        db.query(UserModel).filter(UserModel.id == auth_key.user_id).first()
    )
    if not requesting_admin or not requesting_admin.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required to delete users.",
        )
    if requesting_admin.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin self-deletion via API is disallowed.",
        )

    # --- FIX APPLIED HERE ---
    user_service = UserService()
    try:
        user_service.delete_user(user_id)
        return None
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )
