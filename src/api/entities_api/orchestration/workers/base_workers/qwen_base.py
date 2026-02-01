from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Dict, Generator, Optional

from dotenv import load_dotenv
from projectdavid_common.schemas.enums import StatusEnum
from projectdavid_common.utilities.logging_service import LoggingUtility

from entities_api.orchestration.streaming.hyperbolic import \
    HyperbolicDeltaNormalizer
from src.api.entities_api.dependencies import get_redis
from src.api.entities_api.orchestration.engine.orchestrator_core import \
    OrchestratorCore
from src.api.entities_api.orchestration.mixins.providers import _ProviderMixins

load_dotenv()
LOG = LoggingUtility()


class QwenBaseWorker(_ProviderMixins, OrchestratorCore, ABC):
    """
    Abstract Base for Qwen Providers (Hyperbolic, Together, etc.).
    Handles QwQ-32B/Qwen2.5 specific stream parsing and history preservation.
    """

    def __init__(
        self, *, assistant_id=None, thread_id=None, redis=None, **extra
    ) -> None:
        self._assistant_cache = extra.get("assistant_cache") or {}
        self.redis = redis or get_redis()
        self.assistant_id = assistant_id
        self.thread_id = thread_id
        self.api_key = extra.get("api_key")

        # Default model logic
        self.model_name = extra.get("model_name", "quen/Qwen1_5-32B-Chat")
        self.max_context_window = extra.get("max_context_window", 128000)
        self.threshold_percentage = extra.get("threshold_percentage", 0.8)

        # [NEW] Holding variable for the parsed tool payload to pass between methods
        self._pending_tool_payload: Optional[Dict[str, Any]] = None
        # [NEW] Holding variable for the parsed decision payload
        self._decision_payload: Optional[Dict[str, Any]] = None

        self.setup_services()
        LOG.debug(f"{self.__class__.__name__} ready (assistant={assistant_id})")

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
        stream_reasoning: bool = False,
        api_key: Optional[str] = None,
        **kwargs,
    ) -> Generator[str, None, None]:
        redis = get_redis()
        stream_key = f"stream:{run_id}"
        stop_event = self.start_cancellation_monitor(run_id)

        # Use instance key if not provided
        api_key = api_key or self.api_key

        # --- FIX 1: Early Variable Initialization (Safety) ---
        self._pending_tool_payload = None
        self._decision_payload = None  # Reset decision state

        assistant_reply = ""
        accumulated = ""
        reasoning_reply = ""
        decision_buffer = ""  # [NEW] Buffer for raw decision JSON string
        current_block = None
        # -----------------------------------------------------

        try:

            if mapped := self._get_model_map(model):
                model = mapped

            # 1. Context Window Setup
            ctx = self._set_up_context_window(assistant_id, thread_id, trunk=True)

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

            # 2. Process deltas via Shared Normalizer
            for chunk in HyperbolicDeltaNormalizer.iter_deltas(raw_stream, run_id):
                if stop_event.is_set():
                    break

                ctype, ccontent = chunk["type"], chunk["content"]

                # --- HISTORY RECONSTRUCTION (Tag Injection) ---
                if ctype == "content":
                    if current_block == "fc":
                        accumulated += "</fc>"
                    elif current_block == "think":
                        accumulated += "</think>"
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
                    decision_buffer += ccontent
                    if current_block == "fc":
                        accumulated += "</fc>"
                    elif current_block == "think":
                        accumulated += "</think>"
                    current_block = "decision"

                # --- REFACTOR: Prevent yielding ANY tool artifacts ---
                # We block 'tool_name' and 'call_arguments', but allow 'decision'
                # to pass through if the UI is configured to handle it.
                if ctype not in ("tool_name", "call_arguments"):
                    yield json.dumps(chunk)
                # -------------------------------------------------

                self._shunt_to_redis_stream(redis, stream_key, chunk)

            # 3. Final Close-out
            if current_block == "fc":
                accumulated += "</fc>"
            elif current_block == "think":
                accumulated += "</think>"

            # --- [NEW] Validate and Save Decision Payload ---
            if decision_buffer:
                try:
                    self._decision_payload = json.loads(decision_buffer.strip())
                    LOG.info(f"Decision payload validated: {self._decision_payload}")
                except json.JSONDecodeError as e:
                    LOG.error(f"Failed to parse decision payload: {e}")

            yield json.dumps({"type": "status", "status": "complete", "run_id": run_id})

            # ------------------------------------------------------------------
            # 💉 FIX 2: TIMEOUT PREVENTION (Keep-Alive Heartbeat)
            # ------------------------------------------------------------------
            yield json.dumps(
                {"type": "status", "status": "processing", "run_id": run_id}
            )

            # ------------------------------------------------------------------
            # 🔒 FIX 3: SAFE PERSISTENCE LOGIC
            # ------------------------------------------------------------------
            has_fc = self.parse_and_set_function_calls(accumulated, assistant_reply)
            message_to_save = assistant_reply

            if has_fc:
                try:
                    # Clean tags for JSON parsing
                    raw_json = (
                        accumulated.replace("<fc>", "").replace("</fc>", "").strip()
                    )
                    # Validate JSON structure
                    payload_dict = json.loads(raw_json)

                    # Store as clean JSON
                    message_to_save = json.dumps(payload_dict)

                    # [NEW] Ensure this is set for process_conversation to pick up
                    self._pending_tool_payload = payload_dict

                except Exception as e:
                    LOG.error(f"Error structuring tool calls: {e}")
                    # Fallback to accumulated string so no data is lost
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

        except Exception as exc:
            err = {"type": "error", "content": str(exc)}
            yield json.dumps(err)
            self._shunt_to_redis_stream(redis, stream_key, err)
        finally:
            stop_event.set()

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

        # Phase 2: Check State & Execute Tool Logic
        if self.get_function_call_state() and self._pending_tool_payload:
            # [NEW] Retrieve decision payload
            current_decision = getattr(self, "_decision_payload", None)

            # This yields the Manifest and does the Polling
            # Note: Qwen inherits _ProviderMixins which usually contains _process_tool_calls
            yield from self._process_tool_calls(
                thread_id=thread_id,
                run_id=run_id,
                assistant_id=assistant_id,
                content=self._pending_tool_payload,  # Pass the accumulated payload
                decision=current_decision,  # [NEW] Pass telemetry
                api_key=api_key,
            )

            # Cleanup
            self.set_tool_response_state(False)
            self.set_function_call_state(None)
            self._pending_tool_payload = None
            self._decision_payload = None  # [NEW] Cleanup

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
