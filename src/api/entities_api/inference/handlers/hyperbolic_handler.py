# entities_api/inference/handlers/hyperbolic_handler.py (Pure Dispatcher)

from typing import Any, Generator, Optional, Type

from projectdavid_common.utilities.logging_service import LoggingUtility

from entities_api.inference.cloud_hyperbolic_llama3 import \
    HyperbolicLlama3Inference  # Assumed existing class for Llama
from entities_api.inference.hypherbolic.r1 import \
    HyperbolicR1Inference  # Assumed existing class
# --- Import the SPECIFIC child handler classes ---
# These are the classes that contain the actual business logic
from entities_api.inference.hypherbolic.v3 import \
    HyperbolicV3Inference  # Your provided class
# --- Import supporting modules ---
# Assuming the arbiter is accessible, e.g., passed in __init__ or via a global/DI mechanism
from entities_api.inference.inference_arbiter import InferenceArbiter

logging_utility = LoggingUtility()


class HyperbolicHandler:
    """
    Acts as a pure dispatcher for Hyperbolic requests, delegating to specific
    child handler classes based on the model ID. Contains NO business logic itself.
    """

    # --- Map identifying strings within the unified_model_id to SPECIFIC child handler classes ---
    # Keys should distinguish the model types handled by different classes.
    # Values are the Class objects themselves.
    SUBMODEL_CLASS_MAP: dict[str, Type[Any]] = {
        "deepseek-v3": HyperbolicV3Inference,  # Route to V3 logic class
        "deepseek-r1": HyperbolicR1Inference,  # Route to R1 logic class
        "meta-llama/": HyperbolicLlama3Inference,  # Route Llama models to their logic class
        # Add other routes as needed
    }

    def __init__(self, arbiter: InferenceArbiter):
        """
        Initializes the dispatcher. Requires access to the InferenceArbiter
        to get instances of the specific child handlers.
        """
        self.arbiter = arbiter
        # Sort keys for robust matching (longest match first)
        self._sorted_sub_routes = sorted(
            self.SUBMODEL_CLASS_MAP.keys(), key=len, reverse=True
        )
        logging_utility.info("HyperbolicHandler dispatcher instance created.")

    def _get_specific_handler_instance(self, unified_model_id: str) -> Any:
        """Finds the correct child handler class and gets its instance via the arbiter."""
        SpecificHandlerClass = None
        unified_model_id_lower = unified_model_id.lower()

        # Find the matching class based on the unified ID
        for route_key in self._sorted_sub_routes:
            if route_key.endswith("/") and unified_model_id_lower.startswith(
                route_key
            ):  # Prefix match
                SpecificHandlerClass = self.SUBMODEL_CLASS_MAP[route_key]
                break
            elif (
                not route_key.endswith("/") and route_key in unified_model_id_lower
            ):  # Substring match
                SpecificHandlerClass = self.SUBMODEL_CLASS_MAP[route_key]
                break

        if SpecificHandlerClass is None:
            logging_utility.error(
                f"No specific handler class route found for {unified_model_id} in HyperbolicHandler"
            )
            raise ValueError(
                f"Unsupported or unconfigured model subtype for Hyperbolic dispatch: {unified_model_id}"
            )

        logging_utility.debug(
            f"Dispatching to specific handler class: {SpecificHandlerClass.__name__}"
        )

        # Use the arbiter to get a potentially cached instance of the SPECIFIC child class
        try:
            # The arbiter uses the Class name (e.g., "HyperbolicV3Inference") as the cache key
            specific_handler_instance = self.arbiter.get_provider_instance(
                SpecificHandlerClass
            )
            return specific_handler_instance
        except Exception as e:
            logging_utility.error(
                f"Failed to get instance for {SpecificHandlerClass.__name__} from arbiter: {e}",
                exc_info=True,
            )
            # Decide if this should raise or be handled differently
            raise ValueError(
                f"Failed to get handler instance for {unified_model_id}"
            ) from e

    # --- Delegation Methods ---
    # These methods simply find the right child handler and call the same method on it.

    async def process_conversation(
        self,
        # Pass ALL arguments the child handler's method expects
        thread_id,
        message_id,
        run_id,
        assistant_id,
        model,  # This is the unified_model_id used for routing
        stream_reasoning=False,
        api_key: Optional[str] = None,
        **kwargs,  # Pass through any extra kwargs
    ) -> Generator[str, None, None]:
        """Delegates process_conversation to the specific child handler."""
        logging_utility.debug(
            f"HyperbolicHandler dispatching process_conversation for {model}"
        )
        specific_handler = self._get_specific_handler_instance(
            model
        )  # Find the child instance

        # Call the same method on the child instance, passing all args
        # Use 'async for' since the child method is likely an async generator
        async for chunk in specific_handler.process_conversation(
            thread_id=thread_id,
            message_id=message_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,  # Pass the original ID if the child needs it internally (it might use _get_model_map)
            stream_reasoning=stream_reasoning,
            api_key=api_key,
            **kwargs,
        ):
            yield chunk

    async def stream(
        self,
        # Pass ALL arguments the child handler's method expects
        thread_id: str,
        message_id: str,  # Example: Assuming stream takes these args
        run_id: str,
        assistant_id: str,
        model: Any,  # unified_model_id
        stream_reasoning: bool = True,
        api_key: Optional[str] = None,
        **kwargs,
    ) -> Generator[str, None, None]:
        """Delegates stream to the specific child handler."""
        logging_utility.debug(f"HyperbolicHandler dispatching stream for {model}")
        specific_handler = self._get_specific_handler_instance(model)

        # Call the same method on the child instance
        async for chunk in specific_handler.stream(
            thread_id=thread_id,
            message_id=message_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            stream_reasoning=stream_reasoning,
            api_key=api_key,
            **kwargs,
        ):
            yield chunk
