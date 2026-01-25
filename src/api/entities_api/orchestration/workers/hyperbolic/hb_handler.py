# src/api/entities_api/orchestration/workers/hyperbolic/together_handler.py
from typing import Any, Generator, Optional, Type

from projectdavid_common.utilities.logging_service import LoggingUtility

from entities_api.orchestration.engine.inference_arbiter import \
    InferenceArbiter
from src.api.entities_api.orchestration.workers.hyperbolic.hb_deepseek import \
    HyperbolicDs1
from src.api.entities_api.orchestration.workers.hyperbolic.hb_gpt_oss import \
    HyperbolicGptOssWorker
from src.api.entities_api.orchestration.workers.hyperbolic.hb_llama import \
    HyperbolicLlamaWorker
from src.api.entities_api.orchestration.workers.hyperbolic.hb_quen import \
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
        "meta-llama/": HyperbolicLlamaWorker,
        "Qwen/": HyperbolicQuenQwq32B,
        "openai/gpt-oss-": HyperbolicGptOssWorker,
    }

    def __init__(self, arbiter: InferenceArbiter):
        self.arbiter = arbiter
        logging_utility.info("HyperbolicHandler dispatcher initialized.")

    def _get_specific_handler_instance(self, unified_model_id: str) -> Any:
        prefix = "hyperbolic/"
        sub_model_id = (
            unified_model_id[len(prefix) :].lower()
            if unified_model_id.lower().startswith(prefix)
            else unified_model_id.lower()
        )

        SpecificHandlerClass = None
        for route_key, handler_cls in self.SUBMODEL_CLASS_MAP.items():
            route_key_lc = route_key.lower()
            if route_key_lc.endswith("/") and sub_model_id.startswith(route_key_lc):
                SpecificHandlerClass = handler_cls
                break
            elif route_key_lc in sub_model_id:
                SpecificHandlerClass = handler_cls
                break

        if not SpecificHandlerClass:
            raise ValueError(f"Unsupported Hyperbolic model: {unified_model_id}")

        return self.arbiter.get_provider_instance(SpecificHandlerClass)

    def process_conversation(
        self,
        thread_id: str,
        message_id: Optional[str],
        run_id: str,
        assistant_id: str,
        model: Any,
        stream_reasoning: bool = False,
        api_key: Optional[str] = None,
        **kwargs,
    ) -> Generator[str, None, None]:
        """
        Routes the conversation process.
        Named arguments are automatically filtered from **kwargs.
        """
        worker = self._get_specific_handler_instance(model)

        yield from worker.process_conversation(
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
        message_id: Optional[str],
        run_id: str,
        assistant_id: str,
        model: Any,
        stream_reasoning: bool = False,
        api_key: Optional[str] = None,
        **kwargs,
    ) -> Generator[str, None, None]:
        worker = self._get_specific_handler_instance(model)

        yield from worker.stream(
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
        thread_id: str,
        run_id: str,
        assistant_id: str,
        model: Any = None,
        api_key: Optional[str] = None,
        **kwargs,
    ) -> Generator[str, None, None]:
        worker = self._get_specific_handler_instance(model)

        yield from worker.process_tool_calls(
            thread_id=thread_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            api_key=api_key,
            **kwargs,
        )
