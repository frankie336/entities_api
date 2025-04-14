# src/api/entities_api/dependencies.py

from datetime import datetime
from typing import Optional

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from .db.database import SessionLocal
from .models.models import ApiKey, User

# --- DB Session Dependency ---


def get_db() -> Session:
    """Yields a transactional database session scoped to the request lifecycle."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- API Key Authentication ---

API_KEY_NAME = "X-API-Key"
api_key_header_scheme = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


async def get_api_key(
    api_key_header: Optional[str] = Security(api_key_header_scheme),
    db: Session = Depends(get_db),
) -> ApiKey:
    """
    Authenticates requests using the provided API key.

    Validates:
    - Presence and format
    - Prefix lookup and activity
    - Full key verification (hashed comparison)
    - Optional expiration
    """
    if not api_key_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API Key in 'X-API-Key' header.",
            headers={"WWW-Authenticate": "APIKey"},
        )

    prefix_length = 8
    if len(api_key_header) <= prefix_length:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key format.",
            headers={"WWW-Authenticate": "APIKey"},
        )

    provided_prefix = api_key_header[:prefix_length]

    potential_key = (
        db.query(ApiKey)
        .filter(
            ApiKey.prefix == provided_prefix,
            ApiKey.is_active.is_(True),  # ✅ Fixes E712
        )
        .first()
    )

    if not potential_key or not potential_key.verify_key(api_key_header):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API Key.",
            headers={"WWW-Authenticate": "APIKey"},
        )

    if potential_key.expires_at and potential_key.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key has expired.",
            headers={"WWW-Authenticate": "APIKey"},
        )

    return potential_key


# --- Resolved User from Authenticated Key ---


async def get_current_user(
    api_key_data: ApiKey = Depends(get_api_key),
) -> User:
    """
    Resolves the user associated with the validated API key.

    Relies on a working foreign key or relationship integrity between ApiKey and User.
    """
    if not api_key_data.user:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not resolve user for the provided API key.",
        )
    return api_key_data.user
