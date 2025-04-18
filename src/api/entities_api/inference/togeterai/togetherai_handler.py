# entities_api/inference/togetherai/togetherai_handler.py
from typing import Any, Generator, Optional, Type

from projectdavid_common.utilities.logging_service import LoggingUtility

from entities_api.inference.inference_arbiter import InferenceArbiter
from entities_api.inference.togeterai.together_deepseek_R1 import \
    TogetherDeepSeekR1Inference
from entities_api.inference.togeterai.together_deepseek_v3 import \
    TogetherDeepSeekV3Inference

logging_utility = LoggingUtility()


class TogetherAIHandler:
    """
    Pure synchronous dispatcher for **TogetherAI** model requests.
    It decides which concrete inference class to use based on the
    canonical model id and then streams / processes via that class.
    """

    # ------------------------------------------------------------------ #
    # Mapping: canonical‑model‑id  ➜  concrete inference class
    # ------------------------------------------------------------------ #
    SUBMODEL_CLASS_MAP: dict[str, Type[Any]] = {
        # DeepSeek@TogetherAI
        "deepseek-ai/DeepSeek-R1": TogetherDeepSeekR1Inference,
        "deepseek-ai/DeepSeek-V3": TogetherDeepSeekV3Inference,
        "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B": TogetherDeepSeekR1Inference,
        "deepseek-ai/DeepSeek-R1-Distill-Qwen-14B": TogetherDeepSeekR1Inference,
        "deepseek-ai/DeepSeek-R1-Distill-Llama-70B-free": TogetherDeepSeekR1Inference,
        # Llama@TogetherAI
        "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8": TogetherDeepSeekV3Inference,
        "meta-llama/Llama-4-Scout-17B-16E-Instruct": TogetherDeepSeekV3Inference,
        "meta-llama/Llama-3.3-70B-Instruct-Turbo": TogetherDeepSeekV3Inference,
        "meta-llama/Llama-3.2-11B-Vision-Instruct-Turbo": TogetherDeepSeekV3Inference,
        "meta-llama/Llama-3.2-90B-Vision-Instruct-Turbo": TogetherDeepSeekV3Inference,
        "meta-llama/Llama-Vision-Free": TogetherDeepSeekV3Inference,
        "meta-llama/LlamaGuard-2-8b": TogetherDeepSeekV3Inference,
        # Google Gemma@TogetherAI
        "google/gemma-2-9b-it": TogetherDeepSeekV3Inference,
        # Mistral@TogetherAI
        "mistralai/Mistral-7B-Instruct-v0.2": TogetherDeepSeekV3Inference,
        "mistralai/Mistral-7B-Instruct-v0.3": TogetherDeepSeekV3Inference,
        # Qwen@TogetherAI
        "Qwen/QwQ-32B": TogetherDeepSeekV3Inference,
        "Qwen/Qwen2.5-Coder-32B-Instruct": TogetherDeepSeekV3Inference,
        "Qwen/Qwen2-VL-72B-Instruct": TogetherDeepSeekV3Inference,
    }

    def __init__(self, arbiter: InferenceArbiter):
        self.arbiter = arbiter
        self._sorted_sub_routes = sorted(
            self.SUBMODEL_CLASS_MAP.keys(), key=len, reverse=True
        )
        logging_utility.info("TogetherAIHandler dispatcher initialized.")

    # ------------------------------------------------------------------ #
    #  Dispatcher internals
    # ------------------------------------------------------------------ #
    def _get_specific_handler_instance(self, unified_model_id: str) -> Any:
        """
        Returns the correct concrete inference class instance
        for a given TogetherAI model id.
        """
        prefix = "together-ai/"
        lower_id = unified_model_id.lower()

        # strip off "together-ai/" prefix
        if lower_id.startswith(prefix):
            sub_model_id = lower_id[len(prefix) :]
        else:
            sub_model_id = lower_id
            logging_utility.warning(
                f"Model ID '{unified_model_id}' did not start with '{prefix}'."
            )

        specific_cls: Optional[Type[Any]] = None
        for route_key in self._sorted_sub_routes:
            key_lc = route_key.lower()

            if key_lc.endswith("/") and sub_model_id.startswith(key_lc):
                specific_cls = self.SUBMODEL_CLASS_MAP[route_key]
                break
            if not key_lc.endswith("/") and key_lc in sub_model_id:
                specific_cls = self.SUBMODEL_CLASS_MAP[route_key]
                break

        if specific_cls is None:
            logging_utility.error(
                f"No handler found for model ID '{sub_model_id}' "
                f"(original: '{unified_model_id}')"
            )
            raise ValueError(f"Unsupported TogetherAI model: {unified_model_id}")

        logging_utility.debug(f"Dispatching to: {specific_cls.__name__}")
        return self.arbiter.get_provider_instance(specific_cls)

    # ------------------------------------------------------------------ #
    #  Public streaming / processing methods
    # ------------------------------------------------------------------ #
    def process_conversation(
        self,
        thread_id,
        message_id,
        run_id,
        assistant_id,
        model,
        stream_reasoning: bool = False,
        api_key: Optional[str] = None,
        **kwargs,
    ) -> Generator[str, None, None]:
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
        self,
        thread_id,
        run_id,
        assistant_id,
        model=None,
        api_key: Optional[str] = None,
    ) -> Generator[str, None, None]:
        handler = self._get_specific_handler_instance(model)
        yield from handler.process_function_calls(
            thread_id=thread_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            api_key=api_key,
        )
