# entities_api/inference/inference_arbiter.py

import os
import threading  # Keep for potential future use, though lock removed
from functools import lru_cache
from typing import Any, Type

from projectdavid_common.utilities.logging_service import LoggingUtility
from redis import Redis

# Import the actual AssistantCache class, NOT the dependency function
from entities_api.services.cached_assistant import AssistantCache

logging_utility = LoggingUtility()


class InferenceArbiter:
    def __init__(self, redis: Redis):
        """
        Initializes the InferenceArbiter.

        Args:
            redis: The Redis client instance, injected via FastAPI dependency.
        """
        if not isinstance(redis, Redis):
            # Add type check for robustness during initialization
            raise TypeError(f"Expected a Redis client instance, but got {type(redis)}")

        self._redis = redis  # Store the injected Redis client

        # --- FIX: Create AssistantCache instance directly ---
        # Create the AssistantCache instance ONCE here, using the provided redis client
        # and fetching necessary env vars.
        base_url = os.getenv("BASE_URL")
        admin_api_key = os.getenv("ADMIN_API_KEY")
        if not base_url or not admin_api_key:
            # Log a warning or raise an error if config is missing
            logging_utility.warning(
                "BASE_URL or ADMIN_API_KEY environment variables not set. "
                "AssistantCache fallback to DB might fail."
            )
            # Depending on requirements, you might want to raise ConfigurationError here

        self._assistant_cache = AssistantCache(
            redis=self._redis,
            pd_base_url=base_url,
            pd_api_key=admin_api_key,
        )
        # --- END FIX ---

        logging_utility.info(
            "InferenceArbiter initialized with Redis client and AssistantCache."
        )
        # Note: Removed manual cache dictionary and lock, relying on lru_cache now.

    @lru_cache(maxsize=32)  # Caches based on provider_class
    def _get_or_create_provider_cached(
        self, provider_class: Type[Any], **kwargs
    ) -> Any:
        """
        Factory method using LRU caching to get or create provider instances.
        Now correctly injects both redis and the pre-created assistant_cache.
        """
        if not isinstance(provider_class, type):
            raise TypeError(f"Expected a class type, but got {type(provider_class)}")

        logging_utility.info(  # Changed to INFO for visibility on instance creation
            f"Creating NEW provider instance via LRU cache: {provider_class.__name__}"
        )

        # --- FIX: Pass BOTH redis and the created assistant_cache ---
        # BaseInference.__init__ expects both `redis` and `assistant_cache`
        instance = provider_class(
            redis=self._redis,
            assistant_cache=self._assistant_cache,  # Pass the instance created in __init__
            **kwargs,  # Pass along any other necessary kwargs
        )
        # --- END FIX ---
        return instance

    def get_provider_instance(self, provider_class: Type[Any], **kwargs) -> Any:
        """
        Retrieves a provider instance using LRU caching based on the class type.
        Simplified to directly use the lru_cache-decorated method.
        """
        # The lru_cache on _get_or_create_provider_cached handles the caching.
        # kwargs are passed to handle potential variations in provider init if needed.
        return self._get_or_create_provider_cached(provider_class, **kwargs)

    def clear_cache(self):
        """Clear the LRU cache for provider instances."""
        self._get_or_create_provider_cached.cache_clear()
        logging_utility.info("InferenceArbiter LRU cache cleared.")

    def refresh_provider(self, provider_class: Type[Any], **kwargs) -> Any:
        """Force refresh a specific provider instance by clearing the cache and getting a new one."""
        if not isinstance(provider_class, type):
            raise TypeError(f"Expected a class type, but got {type(provider_class)}")

        class_name = provider_class.__name__
        logging_utility.info(f"Refreshing provider instance for {class_name}")
        # Clear the entire LRU cache (lru_cache doesn't support targeted eviction easily)
        # Alternatively, if specific eviction is critical, revert to manual dict cache.
        self.clear_cache()
        # Get a potentially new instance (will be new if not already created post-clear)
        return self.get_provider_instance(provider_class, **kwargs)

    @property
    def cache_stats(self):
        """Returns statistics about the LRU cache."""
        lru_info = self._get_or_create_provider_cached.cache_info()
        return {
            "lru_hits": lru_info.hits,
            "lru_misses": lru_info.misses,
            "lru_max_size": lru_info.maxsize,
            "lru_current_size": lru_info.currsize,
        }

    # Note: active_providers property is removed as lru_cache doesn't easily expose keys.
    # If needed, you would have to revert to the manual dictionary cache (`_provider_cache`).
