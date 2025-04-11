# entities_api/inference/inference_provider_selector.py

from typing import Any, Type

from projectdavid_common.constants.ai_model_map import MODEL_MAP
from projectdavid_common.utilities.logging_service import LoggingUtility

# Import general top-level handler classes only (not specific sub-model handlers)
from entities_api.inference.azure.azure_handler import AzureHandler
from entities_api.inference.deepseek.deepseek_handler import DeepseekHandler
from entities_api.inference.google.google_handler import GoogleHandler
from entities_api.inference.groq.groq_handler import GroqHandler
from entities_api.inference.hypherbolic.hyperbolic_handler import HyperbolicHandler
from entities_api.inference.local.local_handler import LocalHandler
from entities_api.inference.togeterai.togetherai_handler import TogetherAIHandler

from entities_api.inference.inference_arbiter import InferenceArbiter

logging_utility = LoggingUtility()

# Top-level routing map: model_id prefix -> general handler class
TOP_LEVEL_ROUTING_MAP: dict[str, Type[Any]] = {
    "hyperbolic/": HyperbolicHandler,
    "google/": GoogleHandler,
    "together-ai/": TogetherAIHandler,
    "deepseek-ai/": DeepseekHandler,
    "azure/": AzureHandler,
    "groq": GroqHandler,  # Direct name (no slash) for flat identifiers
    "local": LocalHandler,
}


class InferenceProviderSelector:
    """
    Selects a general handler class (e.g. GoogleHandler) based on top-level
    model ID prefixes and resolves the correct API model name.
    """

    MODEL_MAP = MODEL_MAP

    def __init__(self, arbiter: InferenceArbiter):
        self.arbiter = arbiter
        # Sorted by descending length to ensure longest prefix match
        self._sorted_routing_keys = sorted(
            list(TOP_LEVEL_ROUTING_MAP.keys()), key=len, reverse=True
        )

    def select_provider(self, model_id: str) -> tuple[Any, str]:
        """
        Resolves a general handler instance and API-specific model name
        based on the incoming model_id string.

        Args:
            model_id (str): The user-specified or unified model key.

        Returns:
            Tuple:
              - General handler instance (e.g. GoogleHandler)
              - Resolved API model name (e.g. "gemini-1.5-pro")

        Raises:
            ValueError: If no matching handler class is found or instantiation fails.
        """
        model_id_lookup = model_id.lower().strip()

        # Step 1: Translate to API-specific model name using MODEL_MAP
        api_model_name = self.MODEL_MAP.get(model_id, model_id)

        # Step 2: Determine the appropriate general handler class
        selected_general_class: Type[Any] | None = None
        for prefix in self._sorted_routing_keys:
            if model_id_lookup.startswith(prefix):
                selected_general_class = TOP_LEVEL_ROUTING_MAP[prefix]
                logging_utility.debug(
                    f"Matched prefix '{prefix}' to general handler class {selected_general_class.__name__} for model '{model_id}'"
                )
                break

        # Step 3: Handle missing routing match
        if selected_general_class is None:
            logging_utility.error(f"No routing match for model_id prefix: '{model_id}'")
            raise ValueError(
                f"Invalid or unknown model identifier prefix: '{model_id}'"
            )

        # Step 4: Get instance via the Arbiter (ensures singleton & caching)
        try:
            provider_instance = self.arbiter.get_provider_instance(
                selected_general_class
            )
        except Exception as e:
            logging_utility.error(
                f"Failed to instantiate handler '{selected_general_class.__name__}': {e}"
            )
            raise ValueError(
                f"Handler instantiation failed for model '{model_id}'"
            ) from e

        # Step 5: Return resolved handler and model name
        logging_utility.info(
            f"Handler selected: '{selected_general_class.__name__}' → Model: '{api_model_name}'"
        )
        return provider_instance, api_model_name
