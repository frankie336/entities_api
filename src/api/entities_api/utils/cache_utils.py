import os

from redis import Redis as SyncRedis

from entities_api.cache.assistant_cache import AssistantCache
from entities_api.cache.message_cache import MessageCache


def get_sync_invalidator() -> AssistantCache:
    """
    Creates a short-lived sync connection to Redis for invalidation purposes.
    """
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    # We use a SyncRedis client here because the Service methods are synchronous
    client = SyncRedis.from_url(redis_url, decode_responses=True)

    return AssistantCache(
        redis=client,
        pd_base_url=os.getenv("ASSISTANTS_BASE_URL", ""),
        pd_api_key=os.getenv("ADMIN_API_KEY", ""),
    )


def get_sync_message_cache() -> MessageCache:
    """
    Creates a synchronous MessageCache instance for cache invalidation
    within sync CRUD services.
    """
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    client = SyncRedis.from_url(redis_url, decode_responses=True)

    return MessageCache(redis=client)
