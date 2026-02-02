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
from src.api.entities_api.orchestration.mixins.provider_mixins import _ProviderMixins
from entities_api.clients.delta_normalizer import DeltaNormalizer

load_dotenv()
LOG = LoggingUtility()


class DeepSeekBaseWorker(_ProviderMixins, OrchestratorCore, ABC):

    def __init__(self, *, assistant_id=None, thread_id=None, redis=None, **extra) -> None:
        self._assistant_cache = extra.get("assistant_cache") or {}
        self.redis = redis or get_redis()
        self.assistant_id = assistant_id
        self.thread_id = thread_id
        self.base_url = os.getenv("BASE_URL")
        self.api_key = extra.get("api_key")
        self.model_name = extra.get("model_name", "deepseek-ai/DeepSeek-V3")
        self.max_context_window = extra.get("max_context_window", 128000)
        self.threshold_percentage = extra.get("threshold_percentage", 0.8)

        # Holding variable for the parsed tool payload
        self._pending_tool_payload: Optional[Dict[str, Any]] = None
        # [NEW] Holding variable for the parsed decision payload
        self._decision_payload: Optional[Dict[str, Any]] = None

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
        self._pending_tool_payload = None
        self._decision_payload = None  # Reset decision state

        accumulated: str = ""
        assistant_reply: str = ""
        reasoning_reply: str = ""
        decision_buffer: str = ""  # [NEW] Buffer for raw decision JSON string
        current_block: str | None = None

        try:
            if mapped := self._get_model_map(model):
                model = mapped

            ctx = self._set_up_context_window(assistant_id, thread_id, trunk=True)

            if model == "deepseek-ai/DeepSeek-R1":
                amended = self._build_amended_system_message(assistant_id=assistant_id)
                ctx = self.replace_system_message(ctx, json.dumps(amended, ensure_ascii=False))

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

            # -----------------------------------------------------------
            # DYNAMIC CLIENT EXECUTION
            # -----------------------------------------------------------
            client = self._get_client_instance(api_key=api_key)
            raw_stream = self._execute_stream_request(client, payload)
            # -----------------------------------------------------------

            for chunk in DeltaNormalizer.iter_deltas(raw_stream, run_id):
                if stop_event.is_set():
                    break

                ctype, ccontent = chunk["type"], chunk["content"]

                # --- 1. STATE MANAGEMENT ---
                if ctype == "content":
                    if current_block == "fc":
                        accumulated += "</fc>"
                    elif current_block == "think":
                        accumulated += "</think>"
                    # Note: We don't add </decision> to 'accumulated' because
                    # we want to filter it out of the visible history.
                    current_block = None
                    assistant_reply += ccontent
                    accumulated += ccontent

                elif ctype == "call_arguments":
                    if current_block != "fc":
                        if current_block == "think":
                            accumulated += "</think>"
                        accumulated += "<fc>"
                        current_block = "fc"
                    accumulated += ccontent

                elif ctype == "reasoning":
                    if current_block != "think":
                        if current_block == "fc":
                            accumulated += "</fc>"
                        accumulated += "<think>"
                        current_block = "think"
                    reasoning_reply += ccontent

                # [NEW] Decision Handling
                elif ctype == "decision":
                    # We are in decision mode. We DO NOT add this to 'accumulated'
                    # or 'assistant_reply' so the user doesn't see it in the chat bubble
                    # (unless the UI specifically renders 'decision' type events).

                    # Accumulate for validation/saving
                    decision_buffer += ccontent

                    # Reset other blocks if we jumped straight here
                    if current_block == "fc":
                        accumulated += "</fc>"
                    elif current_block == "think":
                        accumulated += "</think>"
                    current_block = "decision"

                # --- 2. SELECTIVE YIELDING ---
                if ctype == "call_arguments":
                    continue

                # Yield all events, including the new "decision" type, to the UI/Consumer
                yield json.dumps(chunk)
                self._shunt_to_redis_stream(redis, stream_key, chunk)

            # Close blocks
            if current_block == "fc":
                accumulated += "</fc>"
            elif current_block == "think":
                accumulated += "</think>"
            # No need to close 'decision' in 'accumulated' as it wasn't added

            # --- 3. [NEW] Validate and Save Decision Payload ---
            if decision_buffer:
                try:
                    # Clean up any potential leftover newlines or whitespace
                    cleaned_decision = decision_buffer.strip()
                    self._decision_payload = json.loads(cleaned_decision)
                    LOG.info(f"Decision payload validated and saved: {self._decision_payload}")
                except json.JSONDecodeError as e:
                    LOG.error(f"Failed to parse decision payload: {e}. Raw: {decision_buffer}")
                    # Optionally handle partial failures or save raw string

            yield json.dumps({"type": "status", "status": "processing", "run_id": run_id})

            # --- 4. PERSISTENCE & HANDOVER PREP ---
            has_fc = self.parse_and_set_function_calls(accumulated, assistant_reply)
            message_to_save = assistant_reply

            if has_fc:
                try:
                    # Clean tags
                    raw_json = accumulated.replace("<fc>", "").replace("</fc>", "").strip()
                    payload_dict = json.loads(raw_json)
                    message_to_save = json.dumps(payload_dict)
                    self._pending_tool_payload = payload_dict

                except Exception as e:
                    LOG.error(f"Error parsing raw tool JSON: {e}")
                    message_to_save = accumulated

            if message_to_save:
                self.finalize_conversation(message_to_save, thread_id, assistant_id, run_id)

            if has_fc:
                self.project_david_client.runs.update_run_status(
                    run_id, StatusEnum.pending_action.value
                )
            else:
                self.project_david_client.runs.update_run_status(run_id, StatusEnum.completed.value)
                yield json.dumps({"type": "status", "status": "complete", "run_id": run_id})

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
        # Phase 1: Stream Inference
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
        # FIX: We only check if a function call state exists.
        # We removed 'and self._pending_tool_payload' so standard tools
        # work even if there is no special decision payload.
        if self.get_function_call_state():

            # Safely retrieve decision payload (it might be None)
            current_decision = getattr(self, "_decision_payload", None)

            # [NEW] We pass the decision payload if it exists, otherwise None.
            # The Router (process_tool_calls) is now equipped to handle decision=None.
            yield from self.process_tool_calls(
                thread_id=thread_id,
                run_id=run_id,
                assistant_id=assistant_id,
                decision=current_decision,
                api_key=api_key,
            )

            # Cleanup
            self.set_tool_response_state(False)
            self.set_function_call_state(None)

            # Clear specific payloads if they exist
            if hasattr(self, "_pending_tool_payload"):
                self._pending_tool_payload = None
            if hasattr(self, "_decision_payload"):
                self._decision_payload = None

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
