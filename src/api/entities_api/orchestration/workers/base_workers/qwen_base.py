from __future__ import annotations

from abc import ABC

from dotenv import load_dotenv
from projectdavid_common.utilities.logging_service import LoggingUtility

from src.api.entities_api.dependencies import get_redis
from src.api.entities_api.orchestration.engine.orchestrator_core import OrchestratorCore
from src.api.entities_api.orchestration.mixins.providers import _ProviderMixins

load_dotenv()
LOG = LoggingUtility()


class QwenBaseWorker(_ProviderMixins, OrchestratorCore, ABC):
    """
    Abstract Base for Qwen Providers (Hyperbolic, Together, etc.).
    Handles QwQ-32B/Qwen2.5 specific stream parsing and history preservation.
    """

    def __init__(self, *, assistant_id=None, thread_id=None, redis=None, **extra) -> None:
        self._assistant_cache = extra.get("assistant_cache") or {}
        self.redis = redis or get_redis()
        self.assistant_id = assistant_id
        self.thread_id = thread_id
        self.api_key = extra.get("api_key")

        # Default model logic
        self.model_name = extra.get("model_name", "quen/Qwen1_5-32B-Chat")
        self.max_context_window = extra.get("max_context_window", 128000)
        self.threshold_percentage = extra.get("threshold_percentage", 0.8)

        self.setup_services()
        LOG.debug(f"{self.__class__.__name__} ready (assistant={assistant_id})")

    def process_conversation(
        self,
        thread_id,
        message_id,
        run_id,
        assistant_id,
        model,
        api_key=None,
        stream_reasoning=True,
        **kwargs,
    ):
        """Standard Qwen process loop."""
        yield from self.stream(
            thread_id,
            message_id,
            run_id,
            assistant_id,
            model,
            api_key=api_key,
            stream_reasoning=stream_reasoning,
            **kwargs,
        )

        if self.get_function_call_state():
            yield from self.process_tool_calls(
                thread_id, run_id, assistant_id, model=model, api_key=api_key
            )
            self.set_tool_response_state(False)
            self.set_function_call_state(None)

            yield from self.stream(
                thread_id,
                None,
                run_id,
                assistant_id,
                model,
                api_key=api_key,
                stream_reasoning=stream_reasoning,
                **kwargs,
            )
