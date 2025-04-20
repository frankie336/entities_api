# services/cached_assistant.py
import asyncio
import json
import os

from projectdavid import Entity  # Assuming this library is synchronous
from redis.asyncio import Redis  # Import the async Redis client class

REDIS_ASSISTANT_TTL = int(os.getenv("REDIS_ASSISTANT_TTL_SECONDS", "300"))


class AssistantCache:
    # Update type hint to async Redis
    def __init__(self, redis: Redis, pd_base_url: str, pd_api_key: str):
        self.redis = redis
        self.pd_base_url = pd_base_url
        self.pd_api_key = pd_api_key
        # It might be slightly cleaner to instantiate the sync client here if needed only here
        # self.pd_client = Entity(base_url=self.pd_base_url, api_key=self.pd_api_key)

    def _cache_key(self, assistant_id: str):
        return f"assistant:{assistant_id}:config"

    # Make method async and use await
    async def get(self, assistant_id: str):
        raw = await self.redis.get(self._cache_key(assistant_id))
        # json.loads is sync, but usually fast enough unless payload is huge
        return json.loads(raw) if raw else None

    # Make method async and use await
    async def set(self, assistant_id: str, payload: dict):
        # json.dumps is sync, but usually fast enough
        await self.redis.set(
            self._cache_key(assistant_id),
            json.dumps(payload),
            ex=REDIS_ASSISTANT_TTL,
        )

    # Make method async as it calls async get/set
    async def retrieve(self, assistant_id: str):
        # Await the async get method
        cached = await self.get(assistant_id)
        if cached:
            return cached

        # --- Interaction with potentially synchronous 'projectdavid' client ---
        # Instantiate the client here or use one from __init__
        client = Entity(base_url=self.pd_base_url, api_key=self.pd_api_key)

        # If client.assistants.retrieve_assistant and client.tools.list_tools
        # are synchronous network/IO-bound operations, they will block the event loop.
        # Run them in a separate thread using asyncio.to_thread:
        try:
            assistant = await asyncio.to_thread(
                client.assistants.retrieve_assistant, assistant_id=assistant_id
            )
            tools = await asyncio.to_thread(
                client.tools.list_tools, assistant_id=assistant_id, restructure=True
            )
        except Exception as e:
            # Handle exceptions from the synchronous calls appropriately
            # logging_utility.error(...) # Example
            print(
                f"Error retrieving data from projectdavid: {e}"
            )  # Replace with proper logging
            # Decide how to handle failure - re-raise, return None, return default?
            return None  # Or raise an appropriate exception

        # build a JSON‐serializable list of tool definitions:
        # This part is CPU-bound and likely fine to run directly
        clean_tools = [t if isinstance(t, dict) else t.dict() for t in tools]

        payload = {
            "instructions": assistant.instructions,
            "tools": clean_tools,
        }

        # Await the async set method
        await self.set(assistant_id, payload)
        return payload
