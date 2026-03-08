# src/api/entities_api/cache/message_cache.py
import asyncio
import json
import os
from typing import Any, Dict, List, Union

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
    """
    Redis-backed message history cache.

    SDK Entity client removed — all cold-load paths now go directly through
    MessageService (sync) or NativeExecutionService (async), eliminating the
    internal HTTP round-trip and the user-identity mismatch that caused 403s
    after ownership primitives were tightened.
    """

    def __init__(self, redis: Union[SyncRedis, "AsyncRedis"]):
        self.redis = redis

    # ------------------------------------------------------------------
    # Lazy service accessors (avoids circular imports at module load time)
    # ------------------------------------------------------------------

    @property
    def _message_svc(self):
        """
        Synchronous MessageService — used by the sync cold-load path.
        Instantiated once and cached on the instance.
        """
        if not hasattr(self, "_message_svc_instance") or self._message_svc_instance is None:
            from src.api.entities_api.services.message_service import \
                MessageService

            self._message_svc_instance = MessageService()
        return self._message_svc_instance

    @property
    def _native_exec(self):
        """
        NativeExecutionService — used by the async cold-load path.
        Instantiated once and cached on the instance.
        """
        if not hasattr(self, "_native_exec_instance") or self._native_exec_instance is None:
            from src.api.entities_api.services.native_execution_service import \
                NativeExecutionService

            self._native_exec_instance = NativeExecutionService()
        return self._native_exec_instance

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cache_key(self, thread_id: str) -> str:
        return f"thread:{thread_id}:history"

    # ------------------------------------------------------------------
    # Asynchronous Methods
    # ------------------------------------------------------------------

    async def get_history(self, thread_id: str) -> List[Dict]:
        """
        Retrieve history from Redis, falling back to DB on a cache miss.

        Cold-load uses NativeExecutionService.get_formatted_messages which
        calls MessageService.get_formatted_messages_internal directly —
        no ownership check needed (internal orchestration path).
        """
        key = self._cache_key(thread_id)

        if isinstance(self.redis, AsyncRedis):
            raw_list = await self.redis.lrange(key, 0, -1)
        else:
            raw_list = await asyncio.to_thread(self.redis.lrange, key, 0, -1)

        if raw_list:
            return [json.loads(m) for m in raw_list]

        LOG.debug(f"[CACHE] Miss for thread {thread_id}. Performing async cold load.")

        try:
            full_hist = await self._native_exec.get_formatted_messages(thread_id)
        except Exception as e:
            LOG.warning(
                "[CACHE] Async cold load failed for thread %s (%s). Returning empty history.",
                thread_id,
                e,
            )
            return []

        if full_hist:
            await self.set_history(thread_id, full_hist)

        return full_hist or []

    async def set_history(self, thread_id: str, messages: List[Dict]):
        """Overwrite / initialise the cache for a thread."""
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

    # ------------------------------------------------------------------
    # Synchronous Methods (hot path for context building)
    # ------------------------------------------------------------------

    def get_history_sync(self, thread_id: str) -> List[Dict]:
        """
        Retrieve history from Redis, falling back to DB on a cache miss.

        Cold-load uses MessageService.get_formatted_messages_internal —
        no SDK client, no HTTP hop, no ownership check (trusted internal path).
        """
        if not isinstance(self.redis, SyncRedis):
            return []

        key = self._cache_key(thread_id)
        raw_list = self.redis.lrange(key, 0, -1)

        if raw_list:
            return [json.loads(m) for m in raw_list]

        LOG.debug(f"[CACHE-SYNC] Miss for thread {thread_id}. Performing sync cold load.")

        try:
            # _internal variant: no user_id required, no ownership check
            full_hist = self._message_svc.get_formatted_messages_internal(thread_id)
            if full_hist:
                self.set_history_sync(thread_id, full_hist)
            return full_hist or []
        except Exception as e:
            LOG.warning(
                "[CACHE-SYNC] Cold load failed for thread %s (%s). Returning empty history.",
                thread_id,
                e,
            )
            return []

    def set_history_sync(self, thread_id: str, messages: List[Dict]):
        """Synchronous wrapper to initialise the cache."""
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


# ------------------------------------------------------------------
# Standalone factory (imported by mixins and services)
# ------------------------------------------------------------------
def get_sync_message_cache() -> MessageCache:
    """
    Create a synchronous MessageCache instance backed by a SyncRedis client.
    """
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    client = SyncRedis.from_url(redis_url, decode_responses=True)
    return MessageCache(redis=client)
