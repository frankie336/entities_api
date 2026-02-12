"""
Central gate-keeper for inference requests.

* Accepts either a synchronous ``redis.Redis`` or an asynchronous
  ``redis.asyncio.Redis`` client injected by FastAPI.
* Builds (once) a shared ``AssistantCache`` instance.
* Creates a NEW provider instance per call (no caching of workers).
"""

from __future__ import annotations

import os
from typing import Any, Type, Union

from projectdavid_common.utilities.logging_service import LoggingUtility
from redis import Redis as SyncRedis

try:
    from redis.asyncio import Redis as AsyncRedis
except ModuleNotFoundError:
    AsyncRedis = None

from entities_api.cache.assistant_cache import AssistantCache

logging_utility = LoggingUtility()


class InferenceArbiter:
    """
    Provides per-run provider instances and a shared AssistantCache.

    IMPORTANT:
    Provider instances are NOT cached.
    Workers must be isolated per execution run to prevent state bleed.
    """

    def __init__(self, redis: Union[SyncRedis, "AsyncRedis"]) -> None:
        """
        Parameters
        ----------
        redis
            Either a sync ``redis.Redis`` or async ``redis.asyncio.Redis``
            supplied by dependency injection.
        """
        if isinstance(redis, SyncRedis):
            self._redis: SyncRedis = redis

        elif AsyncRedis is not None and isinstance(redis, AsyncRedis):
            # Convert async redis client into sync URL for AssistantCache
            self._redis = SyncRedis.from_url(self._reconstruct_url(redis))

        else:
            raise TypeError(
                f"InferenceArbiter expected redis.Redis or redis.asyncio.Redis, got {type(redis)}"
            )

        base_url = os.getenv("BASE_URL")
        admin_api_key = os.getenv("ADMIN_API_KEY")

        if not base_url or not admin_api_key:
            logging_utility.warning(
                "BASE_URL or ADMIN_API_KEY not set – AssistantCache may fallback to slow DB lookups."
            )

        # Shared infrastructure (safe to reuse)
        self._assistant_cache = AssistantCache(
            redis=self._redis,
            pd_base_url=base_url,
            pd_api_key=admin_api_key,
        )

        logging_utility.info(
            "InferenceArbiter initialised (redis=%s async=%s)",
            type(self._redis).__name__,
            isinstance(redis, AsyncRedis) if AsyncRedis else False,
        )

    # ------------------------------------------------------------------
    # FACTORY METHOD (NO CACHING)
    # ------------------------------------------------------------------

    def get_provider_instance(self, provider_class: Type[Any], **kwargs) -> Any:
        """
        Create a NEW provider instance per invocation.

        This guarantees execution isolation and prevents
        cross-request state contamination.
        """
        if not isinstance(provider_class, type):
            raise TypeError(f"Expected a class type, got {type(provider_class)}")

        logging_utility.info(
            "Creating provider instance (PER RUN): %s",
            provider_class.__name__,
        )

        return provider_class(
            redis=self._redis,
            assistant_cache=self._assistant_cache,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # UTILITIES
    # ------------------------------------------------------------------

    @staticmethod
    def _reconstruct_url(async_client: "AsyncRedis") -> str:
        """Rebuild a redis URL from a redis.asyncio.Redis client."""
        kw = async_client.connection_pool.connection_kwargs

        if "path" in kw:
            return f"unix://{kw['path']}"

        protocol = "rediss" if kw.get("ssl") else "redis"
        host = kw.get("host", "localhost")
        port = kw.get("port", 6379)
        db = kw.get("db", 0)
        password = kw.get("password")

        auth = f":{password}@" if password else ""

        return f"{protocol}://{auth}{host}:{port}/{db}"
