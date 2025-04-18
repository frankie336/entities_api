import threading
from functools import lru_cache

from entities_api.inference.cloud_azure_r1 import AzureR1Cloud
from entities_api.inference.hypherbolic.hyperbolic_deepseek_r1 import \
    HyperbolicR1Inference
from entities_api.inference.hypherbolic.hyperbolic_deepseek_v3 import \
    HyperbolicDeepSeekV3Inference
from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()


class CloudInference:
    def __init__(self):
        self._provider_cache = {}
        self._cache_lock = threading.RLock()  # Thread safety for high concurrency

    @lru_cache(maxsize=8)
    def _create_provider(self, provider_class):
        """Factory method with LRU caching for provider instances"""
        logging_utility.debug(
            f"Initializing new provider instance: {provider_class.__name__}"
        )
        return provider_class()

    def _get_provider(self, provider_class):
        """Thread-safe provider retrieval with double-checked locking"""
        class_name = provider_class.__name__

        with self._cache_lock:
            if class_name not in self._provider_cache:
                instance = self._create_provider(provider_class)
                self._provider_cache[class_name] = instance
        return self._provider_cache[class_name]

    def get_azure_deepseek_r1(self):
        return self._get_provider(AzureR1Cloud)

    def get_hyperbolic_r1(self):
        return self._get_provider(HyperbolicR1Inference)

    def get_hyperbolic_v3(self):
        return self._get_provider(HyperbolicDeepSeekV3Inference)

    # Cache management
    def clear_cache(self):
        """Clear all cached provider instances"""
        with self._cache_lock:
            self._provider_cache.clear()
            self._create_provider.cache_clear()

    def refresh_provider(self, provider_class):
        """Force refresh a specific provider instance"""
        with self._cache_lock:
            self._create_provider.cache_clear()
            if provider_class.__name__ in self._provider_cache:
                del self._provider_cache[provider_class.__name__]
        return self._get_provider(provider_class)

    # Add these properties to monitor performance
    @property
    def cache_stats(self):
        return {
            "current_size": len(self._provider_cache),
            "hits": self._create_provider.cache_info().hits,
            "misses": self._create_provider.cache_info().misses,
            "max_size": self._create_provider.cache_info().max_size,
        }

    @property
    def active_providers(self):
        return list(self._provider_cache.keys())
