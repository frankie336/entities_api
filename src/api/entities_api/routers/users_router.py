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
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    """
    Creates a new user. Requires **Admin** authentication via API Key.

    - **Authentication**: Requires a valid API key in the `X-API-Key` header.
    - **Authorization**: The user associated with the API key must have admin privileges.
    - **Input**: User creation details.
    - **Output**: Detailed information about the newly created user.
    """
    logging_utility.info(
        f"User '{auth_key.user_id}' (Key Prefix: {auth_key.prefix}) requesting to create a new user."
    )

    logging_utility.debug(f"User creation payload: {user_data.model_dump()}")
    requesting_admin = (
        db.query(UserModel).filter(UserModel.id == auth_key.user_id).first()
    )

    if not requesting_admin or not requesting_admin.is_admin:
        logging_utility.warning(
            f"Authorization Failed: User {auth_key.user_id} attempted to create user without admin rights."
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required to create users.",
        )
    logging_utility.info(
        f"Admin user {requesting_admin.id} authorized. Proceeding with user creation."
    )
    user_service = UserService(db)
    try:
        new_user = user_service.create_user(user_data)
        logging_utility.info(
            f"User '{new_user.email}' (ID: {new_user.id}) created successfully by admin {requesting_admin.id}."
        )
        return new_user
    except HTTPException as e:
        logging_utility.error(
            f"HTTP error during user creation by admin {requesting_admin.id}: {e.detail} (Status: {e.status_code})"
        )
        raise e
    except Exception as e:
        logging_utility.error(
            f"Unexpected error during user creation by admin {requesting_admin.id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while creating the user.",
        )


@router.get("/{user_id}", response_model=validation.UserRead)
def get_user(
    user_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    """
    Retrieves details for a specific user.

    - **Authentication**: Requires a valid API key.
    - **Authorization**: Requires the requesting user to be an admin OR the user
      whose details are being requested.
    - **Input**: User ID from path.
    - **Output**: Detailed information about the requested user.
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
        logging_utility.warning(
            f"Authorization Failed: User {auth_key.user_id} attempted to access details for user {user_id}."
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to access this user's details.",
        )
    logging_utility.info(
        f"User {auth_key.user_id} authorized to access user {user_id}."
    )
    user_service = UserService(db)
    try:
        user = user_service.get_user(user_id)
        logging_utility.info(
            f"User {user_id} retrieved successfully by {auth_key.user_id}."
        )
        return user
    except HTTPException as e:
        logging_utility.error(
            f"HTTP error occurred while retrieving user {user_id} for {auth_key.user_id}: {str(e)}"
        )
        raise e
    except Exception as e:
        logging_utility.error(
            f"An unexpected error occurred while retrieving user {user_id} for {auth_key.user_id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.put("/{user_id}", response_model=validation.UserRead)
def update_user(
    user_id: str,
    user_update: UserUpdate,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    """
    Updates details for a specific user.

    - **Authentication**: Requires a valid API key.
    - **Authorization**: Requires the requesting user to be an admin OR the user
      being updated. Non-admins cannot change certain fields (e.g., is_admin).
    - **Input**: User ID from path and update data in body.
    - **Output**: Detailed information about the updated user.
    """
    logging_utility.info(
        f"User '{auth_key.user_id}' requesting to update user ID: {user_id}"
    )
    logging_utility.debug(
        f"Update payload for {user_id}: {user_update.model_dump(exclude_unset=True)}"
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
    if not is_admin_request and (not is_self_request):
        logging_utility.warning(
            f"Authorization Failed: User {auth_key.user_id} attempted to update user {user_id}."
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to update this user.",
        )
    update_data = user_update.model_dump(exclude_unset=True)
    if not is_admin_request:
        if "is_admin" in update_data:
            logging_utility.warning(
                f"Attempt by non-admin user {auth_key.user_id} to modify 'is_admin' field for user {user_id}."
            )
            del update_data["is_admin"]
    logging_utility.info(
        f"User {auth_key.user_id} authorized to update user {user_id}."
    )
    user_service = UserService(db)
    try:
        updated_user = user_service.update_user(user_id, UserUpdate(**update_data))
        logging_utility.info(
            f"User {user_id} updated successfully by {auth_key.user_id}."
        )
        return updated_user
    except HTTPException as e:
        logging_utility.error(
            f"HTTP error occurred while updating user {user_id} for {auth_key.user_id}: {str(e)}"
        )
        raise e
    except Exception as e:
        logging_utility.error(
            f"An unexpected error occurred while updating user {user_id} for {auth_key.user_id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    """
    Deletes a specific user. Requires **Admin** authentication.

    - **Authentication**: Requires a valid API key.
    - **Authorization**: The user associated with the API key must have admin privileges.
      Self-deletion via API is typically disallowed.
    - **Input**: User ID from path.
    - **Output**: 204 No Content on success.
    """
    logging_utility.info(
        f"User '{auth_key.user_id}' requesting to delete user ID: {user_id}"
    )
    requesting_admin = (
        db.query(UserModel).filter(UserModel.id == auth_key.user_id).first()
    )
    if not requesting_admin or not requesting_admin.is_admin:
        logging_utility.warning(
            f"Authorization Failed: User {auth_key.user_id} attempted to delete user {user_id} without admin rights."
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required to delete users.",
        )
    if requesting_admin.id == user_id:
        logging_utility.warning(
            f"Admin user {auth_key.user_id} attempted self-deletion via API."
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin self-deletion via API is disallowed.",
        )
    logging_utility.info(
        f"Admin user {requesting_admin.id} authorized to delete user {user_id}."
    )
    user_service = UserService(db)
    try:
        user_service.delete_user(user_id)
        logging_utility.info(
            f"User {user_id} deleted successfully by admin {requesting_admin.id}."
        )
        return None
    except HTTPException as e:
        logging_utility.error(
            f"HTTP error occurred while deleting user {user_id} by admin {requesting_admin.id}: {str(e)}"
        )
        raise e
    except Exception as e:
        logging_utility.error(
            f"An unexpected error occurred while deleting user {user_id} by admin {requesting_admin.id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )
