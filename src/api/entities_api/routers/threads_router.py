# src/api/entities_api/routers/threads_router.py

from fastapi import APIRouter, Depends, HTTPException, status  # Added status
from httpx import Response
# Import your common ValidationInterface schemas
from projectdavid_common import ValidationInterface
from projectdavid_common.utilities.logging_service import LoggingUtility
from sqlalchemy.orm import Session

# Import API dependencies
from ..dependencies import get_api_key, get_db  # Import get_api_key
from ..models.models import \
    ApiKey as ApiKeyModel  # Import the DB model for type hint
from ..services.threads import ThreadService

# Import your specific request/response serializers if needed for Threads
# (Assuming ThreadCreate is part of ValidationInterface or imported elsewhere)
# from .. import serializers


# Use your common validator instance if needed, or direct schema imports
validation = ValidationInterface()

router = APIRouter(
    prefix="/threads",  # Add prefix here for organization
    tags=["Threads"],  # Add Swagger UI tag
)
logging_utility = LoggingUtility()


@router.post(
    "",  # Path relative to router prefix, so just "" for POST /threads
    response_model=validation.ThreadReadDetailed,
    status_code=status.HTTP_201_CREATED,  # Use status constant for clarity
)
def create_thread(
    thread_data: validation.ThreadCreate,  # Use specific name for input data
    db: Session = Depends(get_db),
    # --- ADD AUTHENTICATION DEPENDENCY ---
    auth_key: ApiKeyModel = Depends(get_api_key),
):
    """
    Creates a new thread. Requires authentication via API Key.

    - **Authentication**: Requires a valid API key in the `X-API-Key` header.
    - **Authorization**: (Implicit) The requesting user (associated with `auth_key`)
      should typically be one of the `participant_ids` in the `thread_data`.
      *Current implementation doesn't explicitly enforce this - consider adding.*
    - **Input**: Thread creation details including participant IDs.
    - **Output**: Detailed information about the newly created thread.
    """
    # Log the authenticated user making the request
    logging_utility.info(
        f"User '{auth_key.user_id}' (Key Prefix: {auth_key.prefix}) requesting to create a new thread."
    )
    logging_utility.info(f"Thread creation data: {thread_data.model_dump()}")

    thread_service = ThreadService(db=db)

    # --- Optional: Authorization Check ---
    # Ensure the authenticated user is part of the thread being created
    # if auth_key.user_id not in thread_data.participant_ids:
    #     logging_utility.warning(f"Authorization Failed: User {auth_key.user_id} tried to create thread without being a participant.")
    #     raise HTTPException(
    #         status_code=status.HTTP_403_FORBIDDEN,
    #         detail="Authenticated user must be a participant in the created thread."
    #     )
    # --- End Optional Authorization Check ---

    try:
        # Pass the validated Pydantic model to the service
        new_thread = thread_service.create_thread(thread_data)
        logging_utility.info(
            f"Thread created successfully with ID: {new_thread.id} by user {auth_key.user_id}"
        )
        return new_thread
    except HTTPException as e:
        # Log HTTP exceptions raised possibly by the service (e.g., invalid participant IDs)
        logging_utility.error(
            f"HTTP error during thread creation by user {auth_key.user_id}: {e.detail} (Status: {e.status_code})"
        )
        raise e
    except Exception as e:
        # Log unexpected errors
        logging_utility.error(
            f"Unexpected error during thread creation by user {auth_key.user_id}: {str(e)}",
            exc_info=True,  # Include traceback info in log
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while creating the thread.",
        )


@router.get("/{thread_id}", response_model=validation.ThreadRead)
def get_thread(thread_id: str, db: Session = Depends(get_db)):
    # --- THIS ENDPOINT STILL NEEDS AUTHENTICATION/AUTHORIZATION ---
    logging_utility.info(f"Received request to get thread with ID: {thread_id}")
    thread_service = ThreadService(db)
    try:
        thread = thread_service.get_thread(thread_id)
        logging_utility.info(f"Thread retrieved successfully with ID: {thread_id}")
        return thread
    except HTTPException as e:
        logging_utility.error(
            f"HTTP error occurred while retrieving thread {thread_id}: {str(e)}"
        )
        raise e
    except Exception as e:
        logging_utility.error(
            f"An unexpected error occurred while retrieving thread {thread_id}: {str(e)}"
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.delete("/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_thread(thread_id: str, db: Session = Depends(get_db)):
    # --- THIS ENDPOINT STILL NEEDS AUTHENTICATION/AUTHORIZATION ---
    logging_utility.info(f"Received request to delete thread with ID: {thread_id}")
    thread_service = ThreadService(db)
    try:
        # Service should ideally return True/False or raise 404 if not found
        deleted = thread_service.delete_thread(thread_id)
        if not deleted:  # Check if service indicates not found
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found"
            )
        logging_utility.info(f"Thread deleted successfully with ID: {thread_id}")
        # Return Response object for 204 as body is ignored
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except HTTPException as e:
        logging_utility.error(
            f"HTTP error occurred while deleting thread {thread_id}: {str(e)}"
        )
        raise e
    except Exception as e:
        logging_utility.error(
            f"An unexpected error occurred while deleting thread {thread_id}: {str(e)}"
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


# NOTE: The endpoint /users/{user_id}/threads might be better placed in users_router.py
# and should also require authentication and authorization (user can only list their own threads).
# If kept here, it needs similar modifications.

# @router.get("/users/{user_id}/threads", ...) # Original path clashes with router prefix
# Possible Fix 1: Move to users_router.py
# Possible Fix 2: Change path here, e.g., "/list/by_user/{user_id}" (less RESTful)
# Possible Fix 3: Don't add prefix to this specific router (less organized)

# Example assuming moved to users_router.py or path adjusted
# @router.get("/list/by_user/{user_id}", response_model=validation.ThreadIds)
# def list_threads_by_user(
#     user_id: str,
#     db: Session = Depends(get_db),
#     auth_key: ApiKeyModel = Depends(get_api_key) # Needs AuthN/AuthZ
# ):
#     # --- NEEDS AUTHORIZATION CHECK: auth_key.user_id must match user_id ---
#     # ... implementation ...
