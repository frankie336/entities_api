# entities_api/inference/handlers/hyperbolic_handler.py (Synchronous Dispatcher)

from typing import Any, Generator, Optional, Type  # Use standard Generator

from projectdavid_common.utilities.logging_service import LoggingUtility

from entities_api.inference.cloud_hyperbolic_llama3 import \
    HyperbolicLlama3Inference
from entities_api.inference.hypherbolic.hyperbolic_deepseek_r1 import \
    HyperbolicR1Inference
# --- Import the SPECIFIC child handler classes ---
# Ensure these paths are correct and the classes themselves are synchronous
from entities_api.inference.hypherbolic.hyperbolic_deepseek_v3 import \
    HyperbolicDeepSeekV3Inference
# --- Import supporting modules ---
from entities_api.inference.inference_arbiter import \
    InferenceArbiter  # Arbiter is sync

logging_utility = LoggingUtility()


class HyperbolicHandler:
    """
    Acts as a pure SYNCHRONOUS dispatcher for Hyperbolic requests, delegating to specific
    child handler classes based on the model ID. Contains NO business logic itself.
    """

    # --- Map identifying strings to SPECIFIC child handler classes ---
    SUBMODEL_CLASS_MAP: dict[str, Type[Any]] = {
        "deepseek-v3": HyperbolicDeepSeekV3Inference,
        "deepseek-r1": HyperbolicR1Inference,
        "meta-llama/": HyperbolicLlama3Inference,
        # Add other routes as needed
    }

    def __init__(self, arbiter: InferenceArbiter):
        """Initializes the dispatcher."""
        self.arbiter = arbiter
        self._sorted_sub_routes = sorted(
            self.SUBMODEL_CLASS_MAP.keys(), key=len, reverse=True
        )
        logging_utility.info(
            "HyperbolicHandler synchronous dispatcher instance created."
        )

    def _get_specific_handler_instance(self, unified_model_id: str) -> Any:
        """Finds the correct child handler class and gets its instance via the arbiter. (Remains Synchronous)"""
        SpecificHandlerClass = None
        unified_model_id_lower = unified_model_id.lower()

        # Find matching class (logic remains the same)
        for route_key in self._sorted_sub_routes:
            if route_key.endswith("/") and unified_model_id_lower.startswith(route_key):
                SpecificHandlerClass = self.SUBMODEL_CLASS_MAP[route_key]
                break
            elif not route_key.endswith("/") and route_key in unified_model_id_lower:
                SpecificHandlerClass = self.SUBMODEL_CLASS_MAP[route_key]
                break

        if SpecificHandlerClass is None:
            logging_utility.error(
                f"No specific handler class route found for {unified_model_id} in HyperbolicHandler"
            )
            raise ValueError(
                f"Unsupported model subtype for Hyperbolic dispatch: {unified_model_id}"
            )

        logging_utility.debug(
            f"Dispatching to specific handler class: {SpecificHandlerClass.__name__}"
        )

        # Use the synchronous arbiter to get the child instance
        try:
            return self.arbiter.get_provider_instance(SpecificHandlerClass)
        except Exception as e:
            logging_utility.error(
                f"Failed to get instance for {SpecificHandlerClass.__name__} from arbiter: {e}",
                exc_info=True,
            )
            raise ValueError(
                f"Failed to get handler instance for {unified_model_id}"
            ) from e

    # --- Delegation Methods - SYNCHRONOUS ---

    def process_conversation(  # Changed to standard def
        self,
        thread_id,
        message_id,
        run_id,
        assistant_id,
        model,  # unified_model_id
        stream_reasoning=False,
        api_key: Optional[str] = None,
        **kwargs,
    ) -> Generator[str, None, None]:  # Changed to standard Generator
        """Delegates process_conversation synchronously."""
        logging_utility.debug(
            f"HyperbolicHandler dispatching process_conversation for {model}"
        )
        specific_handler = self._get_specific_handler_instance(model)

        # Delegate using 'yield from' as the child handler returns a sync generator
        yield from specific_handler.process_conversation(
            thread_id=thread_id,
            message_id=message_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            stream_reasoning=stream_reasoning,
            api_key=api_key,
            **kwargs,
        )

    def stream(  # Changed to standard def
        self,
        thread_id: str,
        message_id: str,
        run_id: str,
        assistant_id: str,
        model: Any,  # unified_model_id
        stream_reasoning: bool = True,
        api_key: Optional[str] = None,
        **kwargs,
    ) -> Generator[str, None, None]:  # Changed to standard Generator
        """Delegates stream synchronously."""
        logging_utility.debug(f"HyperbolicHandler dispatching stream for {model}")
        specific_handler = self._get_specific_handler_instance(model)

        # Delegate using 'yield from' as the child handler returns a sync generator
        yield from specific_handler.stream(
            thread_id=thread_id,
            message_id=message_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            stream_reasoning=stream_reasoning,
            api_key=api_key,
            **kwargs,
        )

    # Add standard 'def' delegation methods for ALL other public methods
    # required by the interface (e.g., process_function_calls)
    # Example:
    def process_function_calls(  # Changed to standard def
        self, thread_id, run_id, assistant_id, model=None, api_key=None
    ) -> Generator[str, None, None]:  # Changed to standard Generator
        """Delegates process_function_calls synchronously."""
        logging_utility.debug(
            f"HyperbolicHandler dispatching process_function_calls for {model}"
        )
        specific_handler = self._get_specific_handler_instance(model)
        # Delegate using 'yield from'
        yield from specific_handler.process_function_calls(
            thread_id=thread_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            api_key=api_key,
        )
