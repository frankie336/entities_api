# entities_api/inference/inference_provider_selector.py (Two-Level Routing)

from typing import Any, Type

from projectdavid_common.constants.ai_model_map import \
    MODEL_MAP  # Your dict[str, str] map
from projectdavid_common.utilities.logging_service import LoggingUtility

from entities_api.inference.handlers.azure import \
    AzureHandler  # Example
from entities_api.inference.handlers.deepseek_handler import \
    DeepseekHandler  # Example
from entities_api.inference.handlers.google_handler import GoogleHandler
from entities_api.inference.handlers.groq_handler import GroqHandler  # Example
# --- STEP 1: Import only the GENERAL handler classes ---
from entities_api.inference.handlers.hyperbolic_handler import \
    HyperbolicHandler
from entities_api.inference.handlers.local_handler import \
    LocalHandler  # Example
# Import other general handlers: TogetherAIHandler, DeepseekHandler, GroqHandler, LocalHandler, AzureHandler...
from entities_api.inference.handlers.togetherai_handler import \
    TogetherAIHandler  # Example
# --- Import supporting modules ---
from entities_api.inference.inference_arbiter import InferenceArbiter

logging_utility = LoggingUtility()

# --- STEP 2: Define the TOP-LEVEL routing map (Prefix -> General Class) ---
TOP_LEVEL_ROUTING_MAP: dict[str, Type[Any]] = {
    "hyperbolic/": HyperbolicHandler,
    "google/": GoogleHandler,
    "together-ai/": TogetherAIHandler,  # Maps the prefix to the general handler
    "deepseek-ai/": DeepseekHandler,  # Maps the prefix to the general handler
    "azure/": AzureHandler,  # Maps the prefix to the general handler
    "groq": GroqHandler,  # Direct mapping for non-prefixed providers
    "local": LocalHandler,  # Direct mapping for non-prefixed providers
}


class InferenceProviderSelector:
    MODEL_MAP = MODEL_MAP

    def __init__(self, arbiter: InferenceArbiter):
        self.arbiter = arbiter
        # Sort keys by length descending for correct prefix matching (e.g., "together-ai/" before "together/")
        self._sorted_routing_keys = sorted(
            list(TOP_LEVEL_ROUTING_MAP.keys()), key=len, reverse=True
        )

    def select_provider(self, model_id: str) -> tuple[Any, str]:
        """
        Selects the general provider handler instance based on the top-level prefix
        and returns the API-specific model name.
        """
        model_id_lookup = model_id.lower().strip()  # For case-insensitive matching

        # 1. API Name Translation (Use original model_id key for lookup)
        api_model_name = self.MODEL_MAP.get(model_id, model_id)

        # 2. Routing to GENERAL handler class using top-level prefix
        selected_general_class: Type[Any] | None = None
        for prefix in self._sorted_routing_keys:
            if model_id_lookup.startswith(prefix):
                selected_general_class = TOP_LEVEL_ROUTING_MAP[prefix]
                logging_utility.debug(
                    f"Matched prefix '{prefix}' to general handler class {selected_general_class.__name__} for model '{model_id}'"
                )
                break

        # 3. Handle Not Found
        if selected_general_class is None:
            logging_utility.error(
                f"Could not determine general handler class for model identifier: '{model_id}'. No matching prefix found in TOP_LEVEL_ROUTING_MAP."
            )
            raise ValueError(
                f"Invalid or unknown model identifier prefix: '{model_id}'"
            )

        # 4. Get GENERAL Handler Instance from Arbiter
        try:
            provider_instance = self.arbiter.get_provider_instance(
                selected_general_class
            )
        except Exception as e:
            logging_utility.error(
                f"Failed to get instance for general handler class {selected_general_class.__name__} from arbiter: {e}"
            )
            raise ValueError(
                f"Failed to instantiate provider for model '{model_id}'."
            ) from e

        # 5. Return the general handler instance and the API-specific model name string
        logging_utility.info(
            f"Selected general handler '{selected_general_class.__name__}' for model '{model_id}' (API name: '{api_model_name}')"
        )
        return provider_instance, api_model_name
