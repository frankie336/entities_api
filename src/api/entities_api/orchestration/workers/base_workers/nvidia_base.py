from __future__ import annotations

import os
from abc import ABC
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from projectdavid_common.utilities.logging_service import LoggingUtility

from src.api.entities_api.dependencies import get_redis
from src.api.entities_api.orchestration.engine.orchestrator_core import \
    OrchestratorCore
from src.api.entities_api.orchestration.mixins.providers import _ProviderMixins

load_dotenv()
LOG = LoggingUtility()


class NvidiaBaseWorker(_ProviderMixins, OrchestratorCore, ABC):

    def __init__(
        self, *, assistant_id=None, thread_id=None, redis=None, **extra
    ) -> None:
        self._assistant_cache = extra.get("assistant_cache") or {}
        self.redis = redis or get_redis()
        self.assistant_id = assistant_id
        self.thread_id = thread_id
        self.base_url = os.getenv("BASE_URL")
        self.api_key = extra.get("api_key")
        self.model_name = extra.get("model_name", "nvidia/NVIDIA-Nemotron-Nano-9B")
        self.max_context_window = extra.get("max_context_window", 128000)
        self.threshold_percentage = extra.get("threshold_percentage", 0.8)

        # [NEW] Holding variable for the parsed tool payload to pass between methods
        self._pending_tool_payload: Optional[Dict[str, Any]] = None

        self.setup_services()
        LOG.debug("NvidiaBaseWorker provider ready (assistant=%s)", assistant_id)

    # ----------------------------------------------------------------------
    # 3. ORCHESTRATOR
    # ----------------------------------------------------------------------
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
        # Phase 1: Stream Inference (Accumulates tool args internally)
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

        # Phase 2: Check State & Execute Tool Logic
        # We check _pending_tool_payload which was set in stream()
        if self.get_function_call_state() and self._pending_tool_payload:

            # This yields the Manifest and does the Polling
            yield from self._process_tool_calls(
                thread_id=thread_id,
                run_id=run_id,
                assistant_id=assistant_id,
                content=self._pending_tool_payload,  # Pass the accumulated payload
                api_key=api_key,
            )

            # Cleanup
            self.set_tool_response_state(False)
            self.set_function_call_state(None)
            self._pending_tool_payload = None

            # Phase 3: Follow-up Stream
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
