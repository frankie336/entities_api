import os
from datetime import datetime
from typing import AsyncGenerator, Optional

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from redis.asyncio import Redis
from sqlalchemy.orm import Session

# Import the single, authoritative 'get_db' function from your central database file.
# This ensures all dependencies use the same database session configuration.
from src.api.entities_api.db.database import get_db

from src.api.entities_api.models.models import ApiKey, User
from src.api.entities_api.services.cached_assistant import AssistantCache


API_KEY_NAME = "X-API-Key"
_api_key_scheme = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


# This dependency now correctly uses the imported get_db, which provides
# sessions from the properly configured engine.
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

    key = (
        db.query(ApiKey)
        .filter(ApiKey.prefix == prefix, ApiKey.is_active.is_(True))
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


async def get_current_user(api_key_data: ApiKey = Depends(get_api_key)) -> User:
    if not api_key_data.user:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not resolve user for the provided API key.",
        )
    return api_key_data.user


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


async def get_redis() -> AsyncGenerator[Redis, None]:
    """
    Async dependency that yields a redis.asyncio.Redis client,
    and closes it at the end of the request.
    """
    client = aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        yield client
    finally:
        await client.close()


async def get_assistant_cache(redis: Redis = Depends(get_redis)) -> AssistantCache:
    """
    Provide an AssistantCache backed by the async Redis client.
    """
    return AssistantCache(
        redis=redis,
        pd_base_url=os.getenv("ASSISTANTS_BASE_URL"),
        pd_api_key=os.getenv("ADMIN_API_KEY"),
    )
