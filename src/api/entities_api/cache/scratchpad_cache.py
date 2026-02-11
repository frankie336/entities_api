# src/api/entities_api/cache/scratchpad_cache.py
import asyncio
import json
import os
import time
from typing import Dict, Optional, Union

from redis import Redis as SyncRedis

try:
    from redis.asyncio import Redis as AsyncRedis
except ImportError:

    class AsyncRedis:
        pass


# Research contexts can be long-lived.
# 86400 = 24 Hours. Enough for a user to come back the next day.
REDIS_SCRATCHPAD_TTL = int(os.getenv("REDIS_SCRATCHPAD_TTL_SECONDS", "86400"))


class ScratchpadCache:
    """
    The Long-Term Working Memory for the Agent.
    Stores the Research Plan, Collected Facts, and Synthesis Drafts.
    Scoped by 'thread_id' so the agent remembers context across multiple turns.
    """

    def __init__(self, redis: Union[SyncRedis, "AsyncRedis"]):
        self.redis = redis

    def _cache_key(self, thread_id: str) -> str:
        """
        Key format: scratchpad:{thread_id}:notebook
        """
        return f"scratchpad:{thread_id}:notebook"

    async def get_scratchpad(self, thread_id: str) -> Dict[str, str]:
        """
        Retrieves the current state of the notebook.
        Returns a dict: {"content": str, "last_updated": float}
        """
        key = self._cache_key(thread_id)

        if isinstance(self.redis, AsyncRedis):
            raw = await self.redis.get(key)
        else:
            raw = await asyncio.to_thread(self.redis.get, key)

        if not raw:
            # Return empty skeleton if nothing exists
            return {"content": "", "last_updated": 0.0}

        return json.loads(raw)

    async def overwrite_scratchpad(self, thread_id: str, content: str):
        """
        Completely replaces the notebook content (Used for 'Re-writing/Cleaning' the plan).
        """
        key = self._cache_key(thread_id)

        payload = {"content": content, "last_updated": time.time()}
        data = json.dumps(payload)

        if isinstance(self.redis, AsyncRedis):
            await self.redis.set(key, data, ex=REDIS_SCRATCHPAD_TTL)
        else:
            await asyncio.to_thread(self.redis.set, key, data, ex=REDIS_SCRATCHPAD_TTL)

    async def append_to_scratchpad(self, thread_id: str, new_notes: str):
        """
        Atomic append operation.
        Used when the agent just wants to jot down a finding without reading everything first.
        """
        # Note: To be truly atomic in Redis, we'd need a LUA script,
        # but for an LLM agent, a GET -> MODIFY -> SET cycle is usually acceptable
        # as the agent is single-threaded per run.

        current_data = await self.get_scratchpad(thread_id)
        existing_content = current_data.get("content", "")

        # Add a clear separator
        updated_content = f"{existing_content}\n\n{new_notes}".strip()

        await self.overwrite_scratchpad(thread_id, updated_content)

    async def clear_scratchpad(self, thread_id: str):
        """Deletes the notebook (e.g., when starting a totally new topic)."""
        key = self._cache_key(thread_id)
        if isinstance(self.redis, AsyncRedis):
            await self.redis.delete(key)
        else:
            await asyncio.to_thread(self.redis.delete, key)
