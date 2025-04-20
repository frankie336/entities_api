# src/api/entities_api/dependencies.py

import os
from datetime import datetime
from typing import AsyncGenerator, Optional  # Added AsyncGenerator

import redis.asyncio as aioredis  # Import the asyncio redis library
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
# Remove sync Redis import if no longer needed elsewhere, otherwise keep both with aliases
# from redis import Redis as SyncRedis # Example if sync is still needed
from redis.asyncio import \
    Redis  # Import the async Redis client class for type hinting
from sqlalchemy.orm import Session

from entities_api.services.cached_assistant import AssistantCache

from .db.database import SessionLocal
from .models.models import ApiKey, User

# ─── Database ────────────────────────────────────────────────────────────────


# No changes needed for get_db
def get_db() -> Session:
    """Yield a transactional DB session, closed at the end of the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ─── API Key Auth ────────────────────────────────────────────────────────────

# No changes needed for API key auth
API_KEY_NAME = "X-API-Key"
_api_key_scheme = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


async def get_api_key(
    api_key_header: Optional[str] = Security(_api_key_scheme),
    db: Session = Depends(get_db),
) -> ApiKey:
    if not api_key_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API Key in 'X-API-Key' header.",
            headers={"WWW-Authenticate": "APIKey"},
        )

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
    if not api_key_data.user:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not resolve user for the provided API key.",
        )
    return api_key_data.user


# ─── Redis & Assistant Cache ─────────────────────────────────────────────────

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
# Removed global synchronous client instantiation:
# redis_client = Redis.from_url(REDIS_URL, decode_responses=True)


async def get_redis() -> (
    AsyncGenerator[Redis, None]
):  # Changed to async def and AsyncGenerator
    """Dependency that yields an async Redis client connection."""
    client = None
    try:
        # Create client within the function for proper async context and resource management
        client = aioredis.from_url(REDIS_URL, decode_responses=True)
        # Note: Depending on the library version and usage pattern (like pubsub),
        # you might need `await client.ping()` here to ensure connection is ready.
        # For simple commands, connection might be established lazily.
        yield client
    finally:
        if client:
            await client.close()  # Ensure the async client connection is closed


# Note: AssistantCache MUST now support an async Redis client.
# If AssistantCache internally uses sync redis methods, it will need updating
# or you'll need a different strategy (e.g., separate sync/async clients).


async def get_assistant_cache(  # Changed to async def
    redis: Redis = Depends(get_redis),  # Depends on the async get_redis now
) -> AssistantCache:
    """
    Provide an AssistantCache backed by the async Redis client.
    Requires AssistantCache to work with an async Redis client instance.
    """
    # Ensure AssistantCache initialization and methods work with the async `redis` object
    return AssistantCache(
        redis=redis,
        pd_base_url=os.getenv("BASE_URL"),
        pd_api_key=os.getenv("ADMIN_API_KEY"),
    )
