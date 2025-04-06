from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from entities_api.dependencies import get_db
from entities_api.serializers import UserUpdate
from entities_api.services.logging_service import LoggingUtility
from entities_api.services.user_service import UserService

from entities_common import ValidationInterface

validation = ValidationInterface()

router = APIRouter()
logging_utility = LoggingUtility()


@router.post("/users", response_model=validation.UserRead)
def create_user(user: validation.UserCreate = None, db: Session = Depends(get_db)):
    logging_utility.info("Received request to create a new user.")
    user_service = UserService(db)
    try:
        new_user = user_service.create_user(user)
        logging_utility.info(f"User created successfully with ID: {new_user.id}")
        return new_user
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while creating user: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(f"An unexpected error occurred while creating user: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.get("/users/{user_id}", response_model=validation.UserRead)
def get_user(user_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to get user with ID: {user_id}")
    user_service = UserService(db)
    try:
        user = user_service.get_user(user_id)
        logging_utility.info(f"User retrieved successfully with ID: {user_id}")
        return user
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while retrieving user {user_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(
            f"An unexpected error occurred while retrieving user {user_id}: {str(e)}"
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.put("/users/{user_id}", response_model=validation.UserRead)
def update_user(user_id: str, user_update: UserUpdate, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to update user with ID: {user_id}")
    user_service = UserService(db)
    try:
        updated_user = user_service.update_user(user_id, user_update)
        logging_utility.info(f"User updated successfully with ID: {user_id}")
        return updated_user
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while updating user {user_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(
            f"An unexpected error occurred while updating user {user_id}: {str(e)}"
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: str, db: Session = Depends(get_db)):
    logging_utility.info(f"Received request to delete user with ID: {user_id}")
    user_service = UserService(db)
    try:
        user_service.delete_user(user_id)
        logging_utility.info(f"User deleted successfully with ID: {user_id}")
        return {"detail": "User deleted successfully"}
    except HTTPException as e:
        logging_utility.error(f"HTTP error occurred while deleting user {user_id}: {str(e)}")
        raise e
    except Exception as e:
        logging_utility.error(
            f"An unexpected error occurred while deleting user {user_id}: {str(e)}"
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")
