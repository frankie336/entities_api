# services/cached_assistant.py
import json
import os
from datetime import timedelta

from projectdavid import Entity
from redis import Redis

REDIS_ASSISTANT_TTL = int(os.getenv("REDIS_ASSISTANT_TTL_SECONDS", "300"))


class AssistantCache:
    def __init__(self, redis: Redis, pd_base_url: str, pd_api_key: str):
        self.redis = redis
        self.pd_base_url = pd_base_url
        self.pd_api_key = pd_api_key

    def _cache_key(self, assistant_id: str):
        return f"assistant:{assistant_id}:config"

    def get(self, assistant_id: str):
        raw = self.redis.get(self._cache_key(assistant_id))
        return json.loads(raw) if raw else None

    def set(self, assistant_id: str, payload: dict):
        self.redis.set(
            self._cache_key(assistant_id),
            json.dumps(payload),
            ex=REDIS_ASSISTANT_TTL,
        )

    def retrieve(self, assistant_id: str):
        # Try cache
        cached = self.get(assistant_id)
        if cached:
            return cached

        # Fallback to one DB call
        client = Entity(base_url=self.pd_base_url, api_key=self.pd_api_key)
        assistant = client.assistants.retrieve_assistant(assistant_id=assistant_id)
        tools = client.tools.list_tools(
            assistant_id=assistant_id, restructure=True
        )

        # build a JSON‐serializable list of tool definitions:
        clean_tools = [
            t if isinstance(t, dict) else t.dict()
            for t in tools
        ]

        payload = {
            "instructions": assistant.instructions,
            "tools": clean_tools,
        }

        self.set(assistant_id, payload)
        return payload
