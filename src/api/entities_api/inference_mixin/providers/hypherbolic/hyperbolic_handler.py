from typing import Any, Generator, Optional, Type

from projectdavid_common.utilities.logging_service import LoggingUtility

from src.api.entities_api.inference.inference_arbiter import InferenceArbiter
from src.api.entities_api.inference_mixin.providers.hypherbolic.hyperbolic_deepseek import \
    HyperbolicDs1
from src.api.entities_api.inference_mixin.providers.hypherbolic.hyperbolic_llama_3_3 import \
    HyperbolicLlama33
from src.api.entities_api.inference_mixin.providers.hypherbolic.hyperbolic_quen_qwq_32b import \
    HyperbolicQuenQwq32B

logging_utility = LoggingUtility()


class HyperbolicHandler:
    """
    Pure synchronous dispatcher for Hyperbolic model requests.
    Delegates to concrete handler classes based on model ID.
    """

    SUBMODEL_CLASS_MAP: dict[str, Type[Any]] = {
        "deepseek-v3": HyperbolicDs1,
        "deepseek-ai/DeepSeek-V3-0324": HyperbolicDs1,
        "deepseek-r1": HyperbolicDs1,
        "meta-llama/": HyperbolicLlama33,
        "Qwen/": HyperbolicQuenQwq32B,
    }

    def __init__(self, arbiter: InferenceArbiter):
        self.arbiter = arbiter
        self._sorted_sub_routes = sorted(
            self.SUBMODEL_CLASS_MAP.keys(), key=len, reverse=True
        )
        logging_utility.info("HyperbolicHandler dispatcher initialized.")

    def _get_specific_handler_instance(self, unified_model_id: str) -> Any:
        prefix = "hyperbolic/"
        sub_model_id = (
            unified_model_id[len(prefix) :].lower()
            if unified_model_id.lower().startswith(prefix)
            else unified_model_id.lower()
        )
        if not unified_model_id.lower().startswith(prefix):
            logging_utility.warning(
                f"Model ID '{unified_model_id}' did not start with expected prefix '{prefix}'."
            )
        SpecificHandlerClass = None
        for route_key, handler_cls in self.SUBMODEL_CLASS_MAP.items():
            route_key_lc = route_key.lower()
            if route_key_lc.endswith("/") and sub_model_id.startswith(route_key_lc):
                logging_utility.debug(f"Matched prefix route: '{route_key}'")
                SpecificHandlerClass = handler_cls
                break
            elif not route_key_lc.endswith("/") and route_key_lc in sub_model_id:
                logging_utility.debug(f"Matched substring route: '{route_key}'")
                SpecificHandlerClass = handler_cls
                break
        if not SpecificHandlerClass:
            logging_utility.error(
                f"No handler found for model ID '{sub_model_id}' (original: '{unified_model_id}')"
            )
            raise ValueError(f"Unsupported Hyperbolic model: {unified_model_id}")
        logging_utility.debug(f"Dispatching to: {SpecificHandlerClass.__name__}")
        try:
            return self.arbiter.get_provider_instance(SpecificHandlerClass)
        except Exception as e:
            logging_utility.error(
                f"Failed to obtain handler instance: {SpecificHandlerClass.__name__}",
                exc_info=True,
            )
            raise ValueError(
                f"Handler resolution failed for model: {unified_model_id}"
            ) from e

    def process_conversation(
        self,
        thread_id,
        message_id,
        run_id,
        assistant_id,
        model,
        stream_reasoning=True,
        api_key: Optional[str] = None,
        **kwargs,
    ) -> Generator[str, None, None]:
        logging_utility.debug(f"Dispatching process_conversation for: {model}")
        handler = self._get_specific_handler_instance(model)
        yield from handler.process_conversation(
            thread_id=thread_id,
            message_id=message_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            stream_reasoning=stream_reasoning,
            api_key=api_key,
            **kwargs,
        )

    def stream(
        self,
        thread_id: str,
        message_id: str,
        run_id: str,
        assistant_id: str,
        model: Any,
        stream_reasoning: bool = True,
        api_key: Optional[str] = None,
        **kwargs,
    ) -> Generator[str, None, None]:
        logging_utility.debug(f"Dispatching stream for: {model}")
        handler = self._get_specific_handler_instance(model)
        yield from handler.stream(
            thread_id=thread_id,
            message_id=message_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            stream_reasoning=stream_reasoning,
            api_key=api_key,
            **kwargs,
        )

    def process_function_calls(
        self, thread_id, run_id, assistant_id, model=None, api_key=None
    ) -> Generator[str, None, None]:
        logging_utility.debug(f"Dispatching process_function_calls for: {model}")
        handler = self._get_specific_handler_instance(model)
        yield from handler.process_function_calls(
            thread_id=thread_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            api_key=api_key,
        )
