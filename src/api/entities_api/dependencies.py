# src/api/entities_api/dependencies.py

import os
from datetime import datetime
from typing import Optional

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from redis import Redis
from sqlalchemy.orm import Session

from entities_api.services.cached_assistant import AssistantCache

from .db.database import SessionLocal
from .models.models import ApiKey, User

# ─── Database ────────────────────────────────────────────────────────────────


def get_db() -> Session:
    """Yield a transactional DB session, closed at the end of the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ─── API Key Auth ────────────────────────────────────────────────────────────

API_KEY_NAME = "X-API-Key"
_api_key_scheme = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


async def get_api_key(
    api_key_header: Optional[str] = Security(_api_key_scheme),
    db: Session = Depends(get_db),
) -> ApiKey:
    """
    Validate X-API-Key header:
      - Must be present and well‑formed
      - Look up active prefix in DB
      - Verify full key (hash)
      - Check expiry
    """
    if not api_key_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API Key in 'X-API-Key' header.",
            headers={"WWW-Authenticate": "APIKey"},
        )

    # fast prefix lookup
    prefix = api_key_header[:8]
    if len(api_key_header) <= len(prefix):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key format.",
            headers={"WWW-Authenticate": "APIKey"},
        )

    key: Optional[ApiKey] = (
        db.query(ApiKey)
        .filter(
            ApiKey.prefix == prefix,
            ApiKey.is_active.is_(True),
        )
        .first()
    )
    if not key or not key.verify_key(api_key_header):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API Key.",
            headers={"WWW-Authenticate": "APIKey"},
        )

    # optional expiration check
    if key.expires_at and key.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key has expired.",
            headers={"WWW-Authenticate": "APIKey"},
        )

    return key


async def get_current_user(
    api_key_data: ApiKey = Depends(get_api_key),
) -> User:
    """Resolve the User linked to the validated ApiKey."""
    if not api_key_data.user:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not resolve user for the provided API key.",
        )
    return api_key_data.user


# ─── Redis & Assistant Cache ─────────────────────────────────────────────────

# instantiate one Redis client (decode_responses so `.get()` returns str)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
redis_client = Redis.from_url(REDIS_URL, decode_responses=True)


def get_redis() -> Redis:
    """Dependency that returns the shared Redis client."""
    return redis_client


def get_assistant_cache(
    redis: Redis = Depends(get_redis),
) -> AssistantCache:
    """
    Provide a per‑process AssistantCache, backed by Redis.
    Caches `{instructions, tools}` for each assistant_id.
    """
    return AssistantCache(
        redis=redis,
        pd_base_url=os.getenv("BASE_URL"),
        pd_api_key=os.getenv("ADMIN_API_KEY"),
    )
