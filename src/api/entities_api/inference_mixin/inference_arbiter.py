"""
Central gate‑keeper for inference requests.

* Accepts **either** a synchronous ``redis.Redis`` **or** an asynchronous
  ``redis.asyncio.Redis`` client that is injected by FastAPI.
* Builds (once) a shared ``AssistantCache`` instance that is passed to every
  provider created through `get_provider_instance`.
* Uses an `@lru_cache` to keep at most\xa032 provider instances alive.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Type, Union

from projectdavid_common.utilities.logging_service import LoggingUtility
from redis import Redis as SyncRedis

try:
    from redis.asyncio import Redis as AsyncRedis
except ModuleNotFoundError:
    AsyncRedis = None
from src.api.entities_api.services.cached_assistant import AssistantCache

logging_utility = LoggingUtility()


class InferenceArbiter:
    """Provides cached access to model‑provider objects and shared AssistantCache."""

    def __init__(self, redis: Union[SyncRedis, "AsyncRedis"]) -> None:
        """Create a new arbiter.

        Parameters
        ----------
        redis
            Either a *sync* ``redis.Redis`` **or** an *async*
            ``redis.asyncio.Redis`` instance supplied by the dependency
            ``get_redis``.
        """
        if isinstance(redis, SyncRedis):
            self._redis: SyncRedis = redis
        elif AsyncRedis is not None and isinstance(redis, AsyncRedis):
            self._redis = SyncRedis.from_url(self._reconstruct_url(redis))
        else:
            raise TypeError(
                f"InferenceArbiter expected a redis.Redis or redis.asyncio.Redis instance, got {type(redis)}"
            )
        base_url = os.getenv("ASSISTANTS_BASE_URL")
        admin_api_key = os.getenv("ADMIN_API_KEY")
        if not base_url or not admin_api_key:
            logging_utility.warning(
                "BASE_URL or ADMIN_API_KEY not set – AssistantCache may fallback to slow DB‑lookups."
            )
        self._assistant_cache = AssistantCache(
            redis=self._redis, pd_base_url=base_url, pd_api_key=admin_api_key
        )
        logging_utility.info(
            "InferenceArbiter initialised (redis=%s async=%s)",
            type(self._redis).__name__,
            isinstance(redis, AsyncRedis) if AsyncRedis else False,
        )

    @lru_cache(maxsize=32)
    def _get_or_create_provider_cached(
        self, provider_class: Type[Any], **kwargs
    ) -> Any:
        """Return a cached provider instance (LRU max 32)."""
        if not isinstance(provider_class, type):
            raise TypeError(f"Expected a class type, got {type(provider_class)}")
        logging_utility.info(
            "Creating NEW provider instance: %s", provider_class.__name__
        )
        return provider_class(
            redis=self._redis, assistant_cache=self._assistant_cache, **kwargs
        )

    def get_provider_instance(self, provider_class: Type[Any], **kwargs) -> Any:
        """Return (cached) provider instance for ``provider_class``."""
        return self._get_or_create_provider_cached(provider_class, **kwargs)

    def clear_cache(self) -> None:
        """Flush **all** cached provider instances."""
        self._get_or_create_provider_cached.cache_clear()
        logging_utility.info("InferenceArbiter LRU cache cleared.")

    def refresh_provider(self, provider_class: Type[Any], **kwargs) -> Any:
        """Force creation of a *new* instance for ``provider_class``."""
        self.clear_cache()
        return self.get_provider_instance(provider_class, **kwargs)

    @property
    def cache_stats(self) -> dict[str, int]:
        """Expose LRU cache statistics."""
        info = self._get_or_create_provider_cached.cache_info()
        return {
            "hits": info.hits,
            "misses": info.misses,
            "max_size": info.maxsize,
            "current_size": info.currsize,
        }

    @staticmethod
    def _reconstruct_url(async_client: "AsyncRedis") -> str:
        """Re‑build a redis URL from an ``redis.asyncio.Redis`` client."""
        kw = async_client.connection_pool.connection_kwargs
        if "path" in kw:
            return f"unix://{kw['path']}"
        protocol = "rediss" if kw.get("ssl") else "redis"
        host = kw.get("host", "localhost")
        port = kw.get("port", 6379)
        db = kw.get("db", 0)
        pw = kw.get("password")
        auth = f":{pw}@" if pw else ""
        return f"{protocol}://{auth}{host}:{port}/{db}"
