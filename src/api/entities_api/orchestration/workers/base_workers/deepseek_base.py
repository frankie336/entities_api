from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, Generator, Optional

from dotenv import load_dotenv
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from src.api.entities_api.dependencies import get_redis
from src.api.entities_api.orchestration.engine.orchestrator_core import OrchestratorCore
from src.api.entities_api.orchestration.mixins.providers import _ProviderMixins
from src.api.entities_api.orchestration.streaming.hyperbolic import (
    HyperbolicDeltaNormalizer,
)

load_dotenv()
LOG = LoggingUtility()


class DeepSeekBaseWorker(_ProviderMixins, OrchestratorCore, ABC):

    def __init__(
        self, *, assistant_id=None, thread_id=None, redis=None, **extra
    ) -> None:
        self._assistant_cache = extra.get("assistant_cache") or {}
        self.redis = redis or get_redis()
        self.assistant_id = assistant_id
        self.thread_id = thread_id
        self.base_url = os.getenv("BASE_URL")
        self.api_key = extra.get("api_key")
        self.model_name = extra.get("model_name", "deepseek-ai/DeepSeek-V3")
        self.max_context_window = extra.get("max_context_window", 128000)
        self.threshold_percentage = extra.get("threshold_percentage", 0.8)

        # [NEW] Holding variable for the parsed tool payload to pass between methods
        self._pending_tool_payload: Optional[Dict[str, Any]] = None

        self.setup_services()
        LOG.debug("Hyperbolic-Ds1 provider ready (assistant=%s)", assistant_id)

    @abstractmethod
    def _get_client_instance(self, api_key: str):
        pass

    @property
    def assistant_cache(self) -> dict:
        return self._assistant_cache

    @assistant_cache.setter
    def assistant_cache(self, value: dict) -> None:
        self._assistant_cache = value

    def get_assistant_cache(self) -> dict:
        return self._assistant_cache

    def stream(
        self,
        thread_id: str,
        message_id: Optional[str],
        run_id: str,
        assistant_id: str,
        model: Any,
        *,
        stream_reasoning: bool = True,
        api_key: Optional[str] = None,
        **kwargs,
    ) -> Generator[str, None, None]:
        redis = get_redis()
        stream_key = f"stream:{run_id}"
        stop_event = self.start_cancellation_monitor(run_id)

        self._current_tool_call_id = None
        # Reset handover state
        self._pending_tool_payload = None

        accumulated: str = ""
        assistant_reply: str = ""
        reasoning_reply: str = ""
        current_block: str | None = None

        try:
            if mapped := self._get_model_map(model):
                model = mapped

            ctx = self._set_up_context_window(assistant_id, thread_id, trunk=True)

            if model == "deepseek-ai/DeepSeek-R1":
                amended = self._build_amended_system_message(assistant_id=assistant_id)
                ctx = self.replace_system_message(
                    ctx, json.dumps(amended, ensure_ascii=False)
                )

            payload = {
                "model": model,
                "messages": ctx,
                "max_tokens": 10000,
                "temperature": kwargs.get("temperature", 0.6),
                "stream": True,
            }

            start_chunk = {"type": "status", "status": "started", "run_id": run_id}
            yield json.dumps(start_chunk)
            self._shunt_to_redis_stream(redis, stream_key, start_chunk)

            client = self._get_client_instance(api_key=api_key)
            raw_stream = client.chat.completions.create(**payload)

            for chunk in HyperbolicDeltaNormalizer.iter_deltas(raw_stream, run_id):
                if stop_event.is_set():
                    break

                ctype, ccontent = chunk["type"], chunk["content"]

                # --- 1. STATE MANAGEMENT (Keep this exactly as is) ---
                if ctype == "content":
                    if current_block == "fc":
                        accumulated += "</fc>"
                    elif current_block == "think":
                        accumulated += "</think>"
                    current_block = None
                    assistant_reply += ccontent

                elif ctype == "call_arguments":
                    if current_block != "fc":
                        if current_block == "think":
                            accumulated += "</think>"
                        accumulated += "<fc>"
                        current_block = "fc"

                elif ctype == "reasoning":
                    if current_block != "think":
                        if current_block == "fc":
                            accumulated += "</fc>"
                        accumulated += "<think>"
                        current_block = "think"
                    reasoning_reply += ccontent

                accumulated += ccontent

                # --- 2. SELECTIVE YIELDING ---
                # We STOP yielding call_arguments directly to the client
                if ctype == "call_arguments":
                    continue

                    # We yield everything else (content, reasoning, etc)
                yield json.dumps(chunk)
                self._shunt_to_redis_stream(redis, stream_key, chunk)

            # Close tags
            if current_block == "fc":
                accumulated += "</fc>"
            elif current_block == "think":
                accumulated += "</think>"

            yield json.dumps(
                {"type": "status", "status": "processing", "run_id": run_id}
            )

            # --- 3. PERSISTENCE & HANDOVER PREP ---
            has_fc = self.parse_and_set_function_calls(accumulated, assistant_reply)
            message_to_save = assistant_reply

            if has_fc:
                try:
                    # Clean tags
                    raw_json = (
                        accumulated.replace("<fc>", "").replace("</fc>", "").strip()
                    )
                    payload_dict = json.loads(raw_json)
                    message_to_save = json.dumps(payload_dict)

                    # [CRITICAL] Store the payload for the next step (process_conversation)
                    self._pending_tool_payload = payload_dict

                except Exception as e:
                    LOG.error(f"Error parsing raw tool JSON: {e}")
                    message_to_save = accumulated

            if message_to_save:
                self.finalize_conversation(
                    message_to_save, thread_id, assistant_id, run_id
                )

            if has_fc:
                self.project_david_client.runs.update_run_status(
                    run_id, StatusEnum.pending_action.value
                )
            else:
                self.project_david_client.runs.update_run_status(
                    run_id, StatusEnum.completed.value
                )
                # Only yield 'complete' if no tool call.
                # If tool call, the tool processor will yield manifests then complete.
                yield json.dumps(
                    {"type": "status", "status": "complete", "run_id": run_id}
                )

        except Exception as exc:
            err = {"type": "error", "content": str(exc)}
            yield json.dumps(err)
            self._shunt_to_redis_stream(redis, stream_key, err)
        finally:
            stop_event.set()

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
