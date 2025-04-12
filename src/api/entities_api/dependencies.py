# src/api/entities_api/dependencies.py
import os
from datetime import datetime
from typing import Optional

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import \
    APIKeyHeader  # Security scheme for API keys in headers
from sqlalchemy.orm import Session

# Adjust imports based on your project structure
from .db.database import \
    SessionLocal  # Your function/factory to get a DB session
from .models.models import ApiKey, User  # Import the ApiKey and User models

# --- Database Dependency ---


def get_db() -> Session:
    """Dependency to provide a database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- API Key Authentication Dependency ---

# Define the header name where the API key is expected
# auto_error=False allows us to provide custom error messages
API_KEY_NAME = "X-API-Key"
api_key_header_scheme = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


async def get_api_key(
    # Use Security to inject the header value using the defined scheme
    api_key_header: Optional[str] = Security(api_key_header_scheme),
    # Inject the database session dependency
    db: Session = Depends(get_db),
) -> ApiKey:
    """
    FastAPI Dependency to authenticate requests using an API key.

    1. Extracts the API key from the 'X-API-Key' header.
    2. Looks up the key prefix in the database for active keys.
    3. Verifies the full key against the stored hash.
    4. Checks for expiration.

    Args:
        api_key_header: The value extracted from the X-API-Key header.
        db: The database session.

    Raises:
        HTTPException(401): If the key is missing, invalid, inactive, or expired.

    Returns:
        The validated ApiKey database object upon successful authentication.
    """
    # 1. Check if the header was provided
    if not api_key_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API Key in 'X-API-Key' header.",
            headers={"WWW-Authenticate": "APIKey"},  # Optional header for 401
        )

    # 2. Extract prefix and lookup potential key
    # Ensure prefix length matches your ApiKey model definition (e.g., 8)
    prefix_length = 8
    if len(api_key_header) <= prefix_length:
        # Provided key is too short to even contain a valid prefix + key part
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key format.",
            headers={"WWW-Authenticate": "APIKey"},
        )

    provided_prefix = api_key_header[:prefix_length]

    # Query for an *active* key matching the prefix
    potential_key = (
        db.query(ApiKey)
        .filter(
            ApiKey.prefix == provided_prefix,
            ApiKey.is_active == True,  # Only consider active keys
        )
        .first()
    )

    # 3. Check if a potential key was found
    if not potential_key:
        # No active key found with this prefix. Use a generic error.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API Key.",  # Generic error
            headers={"WWW-Authenticate": "APIKey"},
        )

    # 4. Verify the full key against the stored hash
    # This uses the `verify_key` method from your ApiKey model
    if not potential_key.verify_key(api_key_header):
        # Prefix matched, but the full key hash doesn't. Generic error.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API Key.",  # Generic error
            headers={"WWW-Authenticate": "APIKey"},
        )

    # 5. Check for expiration
    if potential_key.expires_at and potential_key.expires_at < datetime.utcnow():
        # Key is valid but expired.
        # Optional: You could deactivate the key here in the DB, but be careful
        # with potential race conditions or transaction rollbacks.
        # potential_key.is_active = False
        # db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key has expired.",
            headers={"WWW-Authenticate": "APIKey"},
        )

    # --- (Optional) Update last_used_at ---
    # Consider performance impact - might add latency to every authenticated request.
    # If you need it, uncomment below. It will be committed when the request handler commits.
    # potential_key.last_used_at = datetime.utcnow()
    # db.add(potential_key) # Mark it for update

    # --- Authentication Successful ---
    return potential_key


# --- (Optional) Current User Dependency ---


async def get_current_user(
    # This dependency relies on get_api_key having run successfully
    api_key_data: ApiKey = Depends(get_api_key),
) -> User:
    """
    FastAPI Dependency that retrieves the User associated with the validated API key.

    Args:
        api_key_data: The ApiKey object returned by the `get_api_key` dependency.

    Raises:
        HTTPException(500): If the user cannot be loaded from the ApiKey object
                            (e.g., relationship issue or user deleted).

    Returns:
        The authenticated User database object.
    """
    # The ApiKey object should have the 'user' relationship loaded if defined correctly
    # in the model (back_populates) and depending on lazy loading strategy.
    # If using lazy='select' (default or explicit), accessing api_key_data.user
    # might trigger a separate query here if not already loaded.
    if not api_key_data.user:
        # This could happen if the relationship isn't set up correctly,
        # or if the user was somehow deleted after the key was created
        # but before the cascade delete worked (unlikely but possible).
        # You might want to log this scenario.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load user associated with the provided API key.",
        )
    return api_key_data.user
