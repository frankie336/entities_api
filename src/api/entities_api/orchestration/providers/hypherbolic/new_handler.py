# src/api/entities_api/orchestration/providers/hypherbolic/hyperbolic_handler.py

from typing import Any, Type, Optional, Generator
from projectdavid_common.utilities.logging_service import LoggingUtility
from .models import (
    HyperbolicDs1,
    HyperbolicLlama33,
    HyperbolicQuenQwq32B,
    BaseHyperbolicProvider
)

LOG = LoggingUtility()


class HyperbolicHandler:
    """
    The Factory / Regional Router for Hyperbolic.
    Resolves specific model strings to specialized Worker classes.
    """

    # Map prefixes to the specialized implementation in models.py
    SUBMODEL_MAP: dict[str, Type[Any]] = {
        "deepseek-": HyperbolicDs1,
        "meta-llama/": HyperbolicLlama33,
        "qwen/": HyperbolicQuenQwq32B,
    }

    def __init__(self, arbiter):
        self.arbiter = arbiter
        LOG.info("Hyperbolic Factory Handler initialized.")

    def _resolve_model_class(self, model_id: str) -> Type[Any]:
        """Matches model string to Class. Defaults to Base if no specialty required."""
        clean_id = model_id.lower().replace("hyperbolic/", "")

        for prefix, cls in self.SUBMODEL_MAP.items():
            if clean_id.startswith(prefix):
                LOG.debug(f"Factory matched '{clean_id}' to {cls.__name__}")
                return cls

        LOG.debug(f"No specialty class for '{clean_id}', using BaseHyperbolicProvider")
        return BaseHyperbolicProvider

    def _get_instance(self, model: str) -> Any:
        """Helper to get the cached/instantiated worker from the Arbiter."""
        handler_cls = self._resolve_model_class(model)
        return self.arbiter.get_provider_instance(handler_cls)

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
        worker = self._get_instance(model)
        yield from worker.stream(
            thread_id=thread_id,
            message_id=message_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            stream_reasoning=stream_reasoning,
            api_key=api_key,
            **kwargs
        )

    def process_conversation(self, **kwargs) -> Generator[str, None, None]:
        """Unified entry point that mirrors the stream signature."""
        yield from self.stream(**kwargs)

    def process_function_calls(
        self, thread_id: str, run_id: str, assistant_id: str, model: Any = None, api_key: str = None
    ) -> Generator[str, None, None]:
        """Delegates tool execution to the resolved worker."""
        worker = self._get_instance(model)
        yield from worker.process_function_calls(
            thread_id=thread_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            api_key=api_key
        )
