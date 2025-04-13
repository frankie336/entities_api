# src/api/entities_api/routers/admin_router.py

from fastapi import APIRouter, Depends, HTTPException, status
# Import common schemas from your shared library
from projectdavid_common.schemas.api_key_schemas import (ApiKeyCreateRequest,
                                                         ApiKeyCreateResponse,
                                                         ApiKeyDetails)
# Import logging utility if you want specific admin logs
from projectdavid_common.utilities.logging_service import LoggingUtility
from sqlalchemy.orm import Session

# Import API dependencies
from ..dependencies import get_api_key, get_db
# Import DB Models required for this router
from ..models.models import ApiKey as ApiKeyModel
from ..models.models import User as UserModel
# Import the specific service needed
from ..services.api_key_service import ApiKeyService

# --- Router Setup ---
admin_router = APIRouter(
    prefix="/admin",  # Prefix for all routes in this file
    tags=["Admin"],  # Tag for grouping in Swagger UI documentation
    responses={
        403: {"description": "Admin privileges required"},
        401: {"description": "Authentication required / Invalid API Key"},
    },  # Common responses
)

# Initialize logging if needed for specific admin actions
logging_utility = LoggingUtility()

# --- Admin Endpoint Definition ---


@admin_router.post(
    "/users/{target_user_id}/keys",  # Path relative to prefix: /admin/users/{target_user_id}/keys
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: Create API Key for User",
    description="Allows an authenticated administrator to create a new API key for any specified user.",
)
def admin_create_api_key_for_user(
    target_user_id: str,  # The ID of the user to create the key for (from path)
    request_data: ApiKeyCreateRequest,  # Payload with key_name, expires_in_days (optional)
    db: Session = Depends(get_db),
    auth_key: ApiKeyModel = Depends(
        get_api_key
    ),  # Authenticates the REQUESTER using X-API-Key
):
    """
    Admin Only: Creates an API key for the user specified in the path (`target_user_id`).

    - **Authentication**: Requires a valid Admin API key in the `X-API-Key` header.
    - **Authorization**: The user associated with the authentication key must have `is_admin=True`.
    - **Input**: Target user ID in path, optional key details in body.
    - **Output**: The generated plain API key and its details. **Store the key immediately.**
    """
    logging_utility.info(
        f"Admin request received from user {auth_key.user_id} (Key Prefix: {auth_key.prefix}) to create key for user {target_user_id}."
    )

    # --- Authorization: Check if requester is admin ---
    # Query the User table to get the user object associated with the provided API key
    requesting_user = (
        db.query(UserModel).filter(UserModel.id == auth_key.user_id).first()
    )

    # Verify the user exists and has the admin flag set
    if not requesting_user or not requesting_user.is_admin:
        logging_utility.warning(
            f"Authorization Failed: User {auth_key.user_id} attempted admin operation without admin rights."
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required for this operation.",
        )
    # --- End Authorization Check ---

    logging_utility.info(
        f"Admin user {requesting_user.id} authorized. Proceeding to create key for user {target_user_id}."
    )

    # Proceed to call the service for the target user_id
    service = ApiKeyService(db=db)
    try:
        # Call the *existing* service method, but authorized by an admin for the target user
        plain_key, created_key_record = service.create_key(
            user_id=target_user_id,  # Use TARGET user ID from path here
            key_name=request_data.key_name,
            expires_in_days=request_data.expires_in_days,
        )

        # Format the successful response using Pydantic models
        key_details = ApiKeyDetails.model_validate(created_key_record)
        logging_utility.info(
            f"API Key (Prefix: {key_details.prefix}) created successfully for user {target_user_id} by admin {requesting_user.id}."
        )
        return ApiKeyCreateResponse(plain_key=plain_key, details=key_details)

    except HTTPException as e:
        # Re-raise HTTPExceptions raised by the service (e.g., user not found - 404)
        logging_utility.error(
            f"HTTP error during admin key creation for user {target_user_id}: {e.detail} (Status: {e.status_code})"
        )
        raise e
    except Exception as e:
        # Catch any other unexpected errors during service call
        logging_utility.error(
            f"Unexpected error during admin key creation for user {target_user_id}: {str(e)}",
            exc_info=True,  # Log traceback for unexpected errors
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Admin failed to create API key for user {target_user_id}: An internal error occurred.",
        )


# --- Add other Admin-specific endpoints below if needed ---
# For example: Admin list all users, Admin delete any user, Admin update any user's details etc.
# Make sure to include similar authentication and admin authorization checks.
