# src/api/entities_api/cache/message_cache.py
import asyncio
import json
import os
from typing import Any, Dict, List, Union

from projectdavid import Entity
from redis import Redis as SyncRedis

from src.api.entities_api.services.logging_service import LoggingUtility

try:
    from redis.asyncio import Redis as AsyncRedis
except ImportError:
    # Use a dummy class so isinstance() checks don't crash
    class AsyncRedis:
        pass


LOG = LoggingUtility()
# Conversations usually last longer than assistant configs; setting to 1 hour
REDIS_HISTORY_TTL = int(os.getenv("REDIS_HISTORY_TTL_SECONDS", "3600"))


class MessageCache:
    def __init__(self, redis: Union[SyncRedis, "AsyncRedis"]):
        self.redis = redis
        self.client = Entity(
            base_url=os.getenv("ASSISTANTS_BASE_URL"),
            api_key=os.getenv("ADMIN_API_KEY"),
        )

    def _cache_key(self, thread_id: str) -> str:
        return f"thread:{thread_id}:history"

    # ──────────────────────────────────────────────────────────
    # Asynchronous Methods (Core)
    # ──────────────────────────────────────────────────────────

    async def get_history(self, thread_id: str) -> List[Dict]:
        """Retrieves history from Redis, falling back to DB if empty."""
        key = self._cache_key(thread_id)

        if isinstance(self.redis, AsyncRedis):
            raw_list = await self.redis.lrange(key, 0, -1)
        else:
            raw_list = await asyncio.to_thread(self.redis.lrange, key, 0, -1)

        if raw_list:
            return [json.loads(m) for m in raw_list]

        LOG.debug(f"[CACHE] Miss for thread {thread_id}. Performing cold load.")
        full_hist = await asyncio.to_thread(
            self.client.messages.get_formatted_messages, thread_id, system_message=None
        )

        if full_hist:
            await self.set_history(thread_id, full_hist)

        return full_hist

    async def set_history(self, thread_id: str, messages: List[Dict]):
        """Overwrite/Initialize the cache for a thread."""
        key = self._cache_key(thread_id)
        serialized = [json.dumps(m) for m in messages[-200:]]

        if isinstance(self.redis, AsyncRedis):
            async with self.redis.pipeline(transaction=True) as pipe:
                await pipe.delete(key)
                if serialized:
                    await pipe.rpush(key, *serialized)
                await pipe.expire(key, REDIS_HISTORY_TTL)
                await pipe.execute()
        else:
            await asyncio.to_thread(self.redis.delete, key)
            if serialized:
                await asyncio.to_thread(self.redis.rpush, key, *serialized)
            await asyncio.to_thread(self.redis.expire, key, REDIS_HISTORY_TTL)

    async def append_message(self, thread_id: str, message: Dict):
        key = self._cache_key(thread_id)
        data = json.dumps(message)

        if isinstance(self.redis, AsyncRedis):
            await self.redis.rpush(key, data)
            await self.redis.ltrim(key, -200, -1)
            await self.redis.expire(key, REDIS_HISTORY_TTL)
        else:
            await asyncio.to_thread(self.redis.rpush, key, data)
            await asyncio.to_thread(self.redis.ltrim, key, -200, -1)
            await asyncio.to_thread(self.redis.expire, key, REDIS_HISTORY_TTL)

    async def delete_history(self, thread_id: str):
        key = self._cache_key(thread_id)
        if isinstance(self.redis, AsyncRedis):
            await self.redis.delete(key)
        else:
            await asyncio.to_thread(self.redis.delete, key)

    # ──────────────────────────────────────────────────────────
    # Synchronous Helpers (The Bridge)
    # ──────────────────────────────────────────────────────────

    def delete_history_sync(self, thread_id: str):
        key = self._cache_key(thread_id)
        if isinstance(self.redis, SyncRedis):
            self.redis.delete(key)
        else:
            asyncio.run(self.delete_history(thread_id))

    def get_history_sync(self, thread_id: str) -> List[Dict]:
        if isinstance(self.redis, SyncRedis):
            key = self._cache_key(thread_id)
            raw_list = self.redis.lrange(key, 0, -1)
            if raw_list:
                return [json.loads(m) for m in raw_list]
        return asyncio.run(self.get_history(thread_id))

    def set_history_sync(self, thread_id: str, messages: List[Dict]):
        """Synchronous wrapper to initialize the cache."""
        if isinstance(self.redis, SyncRedis):
            key = self._cache_key(thread_id)
            serialized = [json.dumps(m) for m in messages[-200:]]
            self.redis.delete(key)
            if serialized:
                self.redis.rpush(key, *serialized)
            self.redis.expire(key, REDIS_HISTORY_TTL)
        else:
            asyncio.run(self.set_history(thread_id, messages))

    def append_message_sync(self, thread_id: str, message: Dict):
        if isinstance(self.redis, SyncRedis):
            key = self._cache_key(thread_id)
            data = json.dumps(message)
            self.redis.rpush(key, data)
            self.redis.ltrim(key, -200, -1)
            self.redis.expire(key, REDIS_HISTORY_TTL)
        else:
            asyncio.run(self.append_message(thread_id, message))


# ──────────────────────────────────────────────────────────
# Standalone Factory Function (OUTSIDE THE CLASS)
# ──────────────────────────────────────────────────────────


def get_sync_message_cache() -> MessageCache:
    """
    Standalone factory to create a synchronous MessageCache instance.
    This is what your Mixins will import.
    """
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    client = SyncRedis.from_url(redis_url, decode_responses=True)
    return MessageCache(redis=client)
