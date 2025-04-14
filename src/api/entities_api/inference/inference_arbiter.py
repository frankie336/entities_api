# entities_api/inference/inference_arbiter.py (Cleaned)

import threading
from functools import lru_cache
from typing import Any, Type  # Added Type hints

from projectdavid_common.utilities.logging_service import \
    LoggingUtility  # Adjusted import path based on previous examples

# --- No specific class imports needed here anymore ---


logging_utility = LoggingUtility()


class InferenceArbiter:
    def __init__(self):
        self._provider_cache: dict[str, Any] = {}  # Cache instance per class name
        self._cache_lock = threading.RLock()  # For thread safety

    # Keep the robust caching mechanism for instance creation
    @lru_cache(
        maxsize=32
    )  # Caches the *result* of instantiation for a given class type
    def _create_provider(self, provider_class: Type[Any]) -> Any:
        """Factory method with LRU caching for provider instances."""
        # Type checking is good practice here
        if not isinstance(provider_class, type):
            raise TypeError(f"Expected a class type, but got {type(provider_class)}")
        logging_utility.debug(
            f"Initializing NEW provider instance via LRU cache: {provider_class.__name__}"
        )
        # --- Instance Creation ---
        # This assumes classes have parameterless __init__ or handle their own config
        return provider_class()

    def get_provider_instance(self, provider_class: Type[Any]) -> Any:
        """
        Thread-safe provider instance retrieval using the class type.
        Gets existing instance from cache or creates/caches a new one.
        """
        if not isinstance(provider_class, type):
            raise TypeError(f"Expected a class type, but got {type(provider_class)}")

        class_name = provider_class.__name__

        # Check instance cache first (fast path, no lock needed for read)
        instance = self._provider_cache.get(class_name)
        if instance:
            return instance

        # If not in instance cache, acquire lock and double-check before creating
        with self._cache_lock:
            instance = self._provider_cache.get(class_name)  # Double check
            if not instance:
                logging_utility.debug(
                    f"Instance cache miss for {class_name}. Attempting creation."
                )
                # Call the LRU-cached creation method
                instance = self._create_provider(provider_class)
                self._provider_cache[class_name] = instance  # Store in instance cache
        return instance

    # --- Specific get_xyz methods REMOVED ---
    # --- PROVIDER_CLASSES dictionary REMOVED ---

    # --- Cache management and Monitoring properties remain useful ---
    def clear_cache(self):
        """Clear all cached provider instances."""
        with self._cache_lock:
            self._provider_cache.clear()
            self._create_provider.cache_clear()  # Clear LRU cache too
        logging_utility.info("InferenceArbiter cache cleared.")

    def refresh_provider(self, provider_class: Type[Any]) -> Any:
        """Force refresh a specific provider instance."""
        if not isinstance(provider_class, type):
            raise TypeError(f"Expected a class type, but got {type(provider_class)}")

        class_name = provider_class.__name__
        logging_utility.info(f"Refreshing provider instance for {class_name}")
        with self._cache_lock:
            # Clear the specific entry from LRU if possible (clearing all is safer)
            self._create_provider.cache_clear()  # Clear entire LRU cache
            if class_name in self._provider_cache:
                del self._provider_cache[class_name]  # Clear instance cache entry
        # Get (or create) a fresh instance
        return self.get_provider_instance(provider_class)

    @property
    def cache_stats(self):
        """Returns statistics about the instance and LRU caches."""
        lru_info = self._create_provider.cache_info()
        with self._cache_lock:
            instance_cache_size = len(self._provider_cache)
        return {
            "instance_cache_size": instance_cache_size,
            "lru_hits": lru_info.hits,
            "lru_misses": lru_info.misses,
            "lru_max_size": lru_info.maxsize,
            "lru_current_size": lru_info.currsize,
        }

    @property
    def active_providers(self) -> list[str]:
        """Returns a list of class names currently held in the instance cache."""
        with self._cache_lock:
            return list(self._provider_cache.keys())
