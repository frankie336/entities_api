# entities_api/inference/handlers/hyperbolic_handler.py

from typing import Any, Generator, Optional, Type

from projectdavid_common.utilities.logging_service import LoggingUtility

from entities_api.inference.hypherbolic.hyperbolic_deepseek_r1 import \
    HyperbolicR1Inference
from entities_api.inference.hypherbolic.hyperbolic_deepseek_v3 import \
    HyperbolicDeepSeekV3Inference
from entities_api.inference.hypherbolic.hyperbolic_llama_3_3 import \
    HyperbolicLlama33Inference
from entities_api.inference.hypherbolic.hyperbolic_quen_qwq_32b import \
    HyperbolicQuenQwq32bInference
from entities_api.inference.inference_arbiter import InferenceArbiter

logging_utility = LoggingUtility()


class HyperbolicHandler:
    """
    Pure synchronous dispatcher for Hyperbolic model requests. Delegates to
    concrete handler classes based on model ID. Contains no business logic.
    """

    SUBMODEL_CLASS_MAP: dict[str, Type[Any]] = {
        # DeepSeek variants
        "deepseek-ai/DeepSeek-V3": HyperbolicDeepSeekV3Inference,
        "deepseek-ai/DeepSeek-V3-0324": HyperbolicDeepSeekV3Inference,
        "deepseek-ai/DeepSeek-R1": HyperbolicR1Inference,

        # Meta‑Llama variants (all to HyperbolicLlama33Inference)
        "meta-llama/Llama-3.3-70B-Instruct": HyperbolicLlama33Inference,
        "meta-llama/Meta-Llama-3.1-70B-Instruct": HyperbolicLlama33Inference,
        "meta-llama/Llama-3.2-3B-Instruct": HyperbolicLlama33Inference,
        "meta-llama/Meta-Llama-3-70B-Instruct": HyperbolicLlama33Inference,
        "meta-llama/Meta-Llama-3.1-405B-Instruct": HyperbolicLlama33Inference,
        "meta-llama/Meta-Llama-3.1-8B-Instruct": HyperbolicLlama33Inference,

        # Qwen variant
        "Qwen/QwQ-32B-Preview": HyperbolicQuenQwq32bInference,
        "Qwen/QwQ-32B": HyperbolicQuenQwq32bInference,
        "Qwen/Qwen2.5-Coder-32B-Instruct": HyperbolicQuenQwq32bInference,
        "Qwen/Qwen2.5-72B-Instruct": HyperbolicQuenQwq32bInference,

    }

    def __init__(self, arbiter: InferenceArbiter):
        self.arbiter = arbiter
        self._sorted_sub_routes = sorted(
            self.SUBMODEL_CLASS_MAP.keys(), key=len, reverse=True
        )
        logging_utility.info("HyperbolicHandler dispatcher initialized.")

    def _get_specific_handler_instance(self, unified_model_id: str) -> Any:
        prefix = "hyperbolic/"
        lower_id = unified_model_id.lower()

        # strip off “hyperbolic/” cleanly
        if lower_id.startswith(prefix):
            sub_model_id = lower_id[len(prefix):]
        else:
            sub_model_id = lower_id
            logging_utility.warning(
                f"Model ID '{unified_model_id}' did not start with '{prefix}'."
            )

        SpecificHandlerClass = None
        # iterate original keys so your logging still shows the mixed‑case route_key
        for route_key in self._sorted_sub_routes:
            route_key_lc = route_key.lower()
            # prefix‑style keys (those ending with “/”)
            if route_key_lc.endswith("/") and sub_model_id.startswith(route_key_lc):
                logging_utility.debug(f"Matched prefix route: '{route_key}'")
                SpecificHandlerClass = self.SUBMODEL_CLASS_MAP[route_key]
                break
            # substring keys
            if not route_key_lc.endswith("/") and route_key_lc in sub_model_id:
                logging_utility.debug(f"Matched substring route: '{route_key}'")
                SpecificHandlerClass = self.SUBMODEL_CLASS_MAP[route_key]
                break

        if not SpecificHandlerClass:
            logging_utility.error(
                f"No handler found for model ID '{sub_model_id}' (original: '{unified_model_id}')"
            )
            raise ValueError(f"Unsupported Hyperbolic model: {unified_model_id}")

        logging_utility.debug(f"Dispatching to: {SpecificHandlerClass.__name__}")
        return self.arbiter.get_provider_instance(SpecificHandlerClass)

    def process_conversation(
        self,
        thread_id,
        message_id,
        run_id,
        assistant_id,
        model,
        stream_reasoning=False,
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
