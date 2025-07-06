import asyncio
import json
import os
from typing import Union

from projectdavid import Entity
from redis import Redis as SyncRedis

try:
    from redis.asyncio import Redis as AsyncRedis
except ImportError:
    AsyncRedis = None
REDIS_ASSISTANT_TTL = int(os.getenv("REDIS_ASSISTANT_TTL_SECONDS", "300"))


class AssistantCache:

    def __init__(
        self, redis: Union[SyncRedis, "AsyncRedis"], pd_base_url: str, pd_api_key: str
    ):
        self.redis = redis
        self.pd_base_url = pd_base_url
        self.pd_api_key = pd_api_key

    def _cache_key(self, assistant_id: str) -> str:
        return f"assistant:{assistant_id}:config"

    async def get(self, assistant_id: str):
        key = self._cache_key(assistant_id)
        if AsyncRedis is not None and isinstance(self.redis, AsyncRedis):
            raw = await self.redis.get(key)
        else:
            raw = await asyncio.to_thread(self.redis.get, key)
        return json.loads(raw) if raw else None

    async def set(self, assistant_id: str, payload: dict):
        key = self._cache_key(assistant_id)
        data = json.dumps(payload)
        if AsyncRedis is not None and isinstance(self.redis, AsyncRedis):
            await self.redis.set(key, data, ex=REDIS_ASSISTANT_TTL)
        else:
            await asyncio.to_thread(self.redis.set, key, data, ex=REDIS_ASSISTANT_TTL)

    async def retrieve(self, assistant_id: str):
        cached = await self.get(assistant_id)
        if cached:
            return cached
        client = Entity(base_url=self.pd_base_url, api_key=self.pd_api_key)
        assistant = await asyncio.to_thread(
            client.assistants.retrieve_assistant, assistant_id=assistant_id
        )
        tools = await asyncio.to_thread(
            client.tools.list_tools, assistant_id=assistant_id, restructure=True
        )
        clean_tools = [t if isinstance(t, dict) else t.dict() for t in tools]
        payload = {"instructions": assistant.instructions, "tools": clean_tools}
        await self.set(assistant_id, payload)
        return payload

    def retrieve_sync(self, assistant_id: str):
        """
        Synchronous wrapper for your BaseInference class.
        """
        return asyncio.run(self.retrieve(assistant_id))
