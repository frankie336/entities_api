import threading
from typing import Any, Type

from projectdavid_common.constants.ai_model_map import MODEL_MAP
from projectdavid_common.utilities.logging_service import LoggingUtility

from src.api.entities_api.inference.azure.azure_handler import AzureHandler
from src.api.entities_api.inference.deepseek.deep_seek_handler import \
    DeepseekHandler
from src.api.entities_api.inference.groq.groq_handler import GroqHandler
from src.api.entities_api.inference.hypherbolic.hyperbolic_handler import \
    HyperbolicHandler
from src.api.entities_api.inference.inference_arbiter import InferenceArbiter
from src.api.entities_api.inference.local.local_handler import LocalHandler
from src.api.entities_api.inference.togeterai.togetherai_handler import \
    TogetherAIHandler
from src.api.entities_api.inference_mixin.providers.google.google_handler import \
    GoogleHandler

logging_utility = LoggingUtility()
TOP_LEVEL_ROUTING_MAP: dict[str, Type[Any]] = {
    "hyperbolic/": HyperbolicHandler,
    "google/": GoogleHandler,
    "together-ai/": TogetherAIHandler,
    "deepseek-ai/": DeepseekHandler,
    "azure/": AzureHandler,
    "groq": GroqHandler,
    "local": LocalHandler,
}


class InferenceProviderSelector:
    """
    Selects and INSTANTIATES a general handler class (e.g. GoogleHandler)
    based on top-level model ID prefixes, passing the arbiter instance.
    Also resolves the correct API model name.
    Manages caching for the general handler instances.
    """

    MODEL_MAP = MODEL_MAP

    def __init__(self, arbiter: InferenceArbiter):
        self.arbiter = arbiter
        self._general_handler_cache: dict[str, Any] = {}
        self._cache_lock = threading.RLock()
        self._sorted_routing_keys = sorted(
            list(TOP_LEVEL_ROUTING_MAP.keys()), key=len, reverse=True
        )

    def _get_or_create_general_handler(self, handler_class: Type[Any]) -> Any:
        """Gets from cache or creates/caches the GENERAL handler instance, passing arbiter."""
        class_name = handler_class.__name__
        with self._cache_lock:
            instance = self._general_handler_cache.get(class_name)
        if instance:
            logging_utility.debug(f"Cache hit for general handler: {class_name}")
            return instance
        with self._cache_lock:
            instance = self._general_handler_cache.get(class_name)
            if not instance:
                logging_utility.debug(
                    f"Cache miss for general handler: {class_name}. Creating instance."
                )
                try:
                    instance = handler_class(self.arbiter)
                    self._general_handler_cache[class_name] = instance
                except Exception as e:
                    logging_utility.error(
                        f"Failed to instantiate general handler {class_name}: {e}",
                        exc_info=True,
                    )
                    raise ValueError(
                        f"Instantiation failed for handler {class_name}"
                    ) from e
        return instance

    def select_provider(self, model_id: str) -> tuple[Any, str]:
        """
        Resolves a general handler instance and API-specific model name
        based on the incoming model_id string.
        """
        model_id_lookup = model_id.lower().strip()
        api_model_name = self.MODEL_MAP.get(model_id, model_id)
        selected_general_class: Type[Any] | None = None
        for prefix in self._sorted_routing_keys:
            if model_id_lookup.startswith(prefix):
                selected_general_class = TOP_LEVEL_ROUTING_MAP[prefix]
                logging_utility.debug(
                    f"Matched prefix '{prefix}' to general handler class {selected_general_class.__name__} for model '{model_id}'"
                )
                break
        if selected_general_class is None:
            logging_utility.error(f"No routing match for model_id prefix: '{model_id}'")
            raise ValueError(
                f"Invalid or unknown model identifier prefix: '{model_id}'"
            )
        try:
            provider_instance = self._get_or_create_general_handler(
                selected_general_class
            )
        except ValueError as e:
            logging_utility.error(
                f"Provider selection failed for model '{model_id}': {e}"
            )
            raise ValueError(
                f"Handler instantiation failed for model '{model_id}'"
            ) from e
        except Exception as e:
            logging_utility.error(
                f"Unexpected error getting handler instance for {selected_general_class.__name__}: {e}",
                exc_info=True,
            )
            raise ValueError(
                f"Failed to get handler instance for model '{model_id}'"
            ) from e
        logging_utility.info(
            f"Handler selected: '{selected_general_class.__name__}' → Model: '{api_model_name}'"
        )
        return (provider_instance, api_model_name)
