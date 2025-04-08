import threading
from functools import lru_cache

from entities_api.inference.cloud_azure_r1 import AzureR1Cloud
from entities_api.inference.cloud_deepseek_r1 import DeepSeekR1Cloud
from entities_api.inference.cloud_deepseek_v3 import DeepSeekV3Cloud
from entities_api.inference.cloud_groq_deepseekr1_llama import GroqCloud
from entities_api.inference.cloud_hyperbolic_llama3 import HyperbolicLlama3Inference
from entities_api.inference.cloud_hyperbolic_r1 import HyperbolicR1Inference
from entities_api.inference.cloud_hyperbolic_v3 import HyperbolicV3Inference
from entities_api.inference.cloud_together_ai_llama2 import TogetherLlama2Inference
from entities_api.inference.cloud_together_ai_r1 import TogetherR1Inference
from entities_api.inference.cloud_together_ai_v3 import TogetherV3Inference
from entities_api.inference.local_inference import (  # New local inference provider
    LocalInference,
)
from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()


class InferenceArbiter:
    def __init__(self):
        self._provider_cache = {}
        self._cache_lock = threading.RLock()  # For thread safety

    @lru_cache(maxsize=16)
    def _create_provider(self, provider_class):
        """Factory method with LRU caching for provider instances."""
        logging_utility.debug(
            f"Initializing new provider instance: {provider_class.__name__}"
        )
        return provider_class()

    def _get_provider(self, provider_class):
        """Thread-safe provider retrieval with double-checked locking."""
        class_name = provider_class.__name__
        with self._cache_lock:
            if class_name not in self._provider_cache:
                instance = self._create_provider(provider_class)
                self._provider_cache[class_name] = instance
        return self._provider_cache[class_name]

    # Provider access methods for cloud providers:
    def get_deepseek_r1(self):
        return self._get_provider(DeepSeekR1Cloud)

    def get_deepseek_v3(self):
        return self._get_provider(DeepSeekV3Cloud)

    def get_groq(self):
        return self._get_provider(GroqCloud)

    def get_azure_r1(self):
        return self._get_provider(AzureR1Cloud)

    def get_hyperbolic_r1(self):
        return self._get_provider(HyperbolicR1Inference)

    def get_hyperbolic_v3(self):
        return self._get_provider(HyperbolicV3Inference)

    def get_hyperbolic_llama3(self):
        return self._get_provider(HyperbolicLlama3Inference)

    def get_together_llama2(self):
        return self._get_provider(TogetherLlama2Inference)

    def get_together_r1(self):
        return self._get_provider(TogetherR1Inference)

    def get_together_v3(self):
        return self._get_provider(TogetherV3Inference)

    # Provider access method for local inference:
    def get_local(self):
        return self._get_provider(LocalInference)

    # Cache management
    def clear_cache(self):
        """Clear all cached provider instances."""
        with self._cache_lock:
            self._provider_cache.clear()
            self._create_provider.cache_clear()

    def refresh_provider(self, provider_class):
        """Force refresh a specific provider instance."""
        with self._cache_lock:
            self._create_provider.cache_clear()
            if provider_class.__name__ in self._provider_cache:
                del self._provider_cache[provider_class.__name__]
        return self._get_provider(provider_class)

    # Monitoring properties
    @property
    def cache_stats(self):
        info = self._create_provider.cache_info()
        return {
            "current_size": len(self._provider_cache),
            "hits": info.hits,
            "misses": info.misses,
            "max_size": info.max_size,
        }

    @property
    def active_providers(self):
        return list(self._provider_cache.keys())
