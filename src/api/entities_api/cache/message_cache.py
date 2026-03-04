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

    class AsyncRedis:
        pass


LOG = LoggingUtility()
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

    def get_history_sync(self, thread_id: str) -> List[Dict]:
        """
        Synchronous history retrieval with safe cache-miss handling.

        Previously fell through to asyncio.run(self.get_history(...)) on a
        cache miss, which crashes with "asyncio.run() cannot be called from a
        running event loop" when invoked from within FastAPI's async context
        (e.g. _set_up_context_window → get_history_sync on a brand-new
        ephemeral thread that has never been cached).

        Fix: on a cache miss with SyncRedis, call the SDK client synchronously
        (it is a blocking call) and populate the cache via set_history_sync,
        keeping everything in the sync domain with zero event-loop touching.

        AsyncRedis path: callers in the async domain must use
        await get_history() directly. This path returns [] as a safe
        no-op fallback and logs a warning so the condition is visible.
        """
        key = self._cache_key(thread_id)

        if isinstance(self.redis, SyncRedis):
            raw_list = self.redis.lrange(key, 0, -1)
            if raw_list:
                return [json.loads(m) for m in raw_list]

            # Cache miss — fetch synchronously, no asyncio.run()
            LOG.debug(f"[CACHE-SYNC] Miss for thread {thread_id}. Cold load via SDK.")
            full_hist = self.client.messages.get_formatted_messages(
                thread_id, system_message=None
            )
            if full_hist:
                self.set_history_sync(thread_id, full_hist)
            return full_hist or []

        # AsyncRedis path — asyncio.run() would crash here too.
        # Callers in the async domain should await get_history() directly.
        LOG.warning(
            "[CACHE-SYNC] get_history_sync called with AsyncRedis — "
            "this path should not be reached from async context. "
            "Use await get_history() instead."
        )
        return []

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

    def delete_history_sync(self, thread_id: str):
        key = self._cache_key(thread_id)
        if isinstance(self.redis, SyncRedis):
            self.redis.delete(key)
        else:
            asyncio.run(self.delete_history(thread_id))

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
