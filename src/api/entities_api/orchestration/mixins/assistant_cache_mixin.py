from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from redis.asyncio import Redis

    # FIX: Import strictly for type hints to avoid circular dependency errors
    from entities_api.cache.assistant_cache import AssistantCache


class AssistantCacheMixin:
    """
    Hybrid Mixin:
    1. Prioritizes explicit injection (via init).
    2. Falls back to ServiceRegistry/Lazy loading (for legacy consistency).
    """

    # Type hint works thanks to 'from __future__ import annotations'
    # and the TYPE_CHECKING block above.
    _assistant_cache: Optional[AssistantCache] = None

    @property
    def assistant_cache(self) -> AssistantCache:
        # 1. Fast Path: It was injected via __init__ (The "New Style")
        if self._assistant_cache:
            return self._assistant_cache

        # 2. Lazy Path: Use ServiceRegistryMixin logic (The "Old/Current Style")
        # This prevents breaking classes that don't have __init__ injection yet.
        if hasattr(self, "_get_service"):
            return self._get_service(
                "AssistantCache"
            )  # Pass string or class if available

        # 3. Last Resort: Construct it if 'redis' is available on 'self'
        # (Useful for InferenceArbiter or classes with raw Redis access)
        if hasattr(self, "redis") and self.redis:
            # FIX: Local import here is required so the code works at runtime
            # without causing a top-level circular import.
            from entities_api.cache.assistant_cache import AssistantCache

            # Create a cached reference so we don't rebuild it every call
            self._assistant_cache = AssistantCache(
                redis=self.redis,
                pd_base_url=os.getenv("ASSISTANTS_BASE_URL"),
                pd_api_key=os.getenv("ADMIN_API_KEY"),
            )
            return self._assistant_cache

        # 4. If all fail, then we have a configuration error
        raise ValueError(
            f"AssistantCache could not be resolved in {self.__class__.__name__}. "
            "Ensure it is injected via __init__, or that the class inherits ServiceRegistryMixin."
        )
