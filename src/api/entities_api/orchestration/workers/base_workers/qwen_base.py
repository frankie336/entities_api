from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, Generator, Optional

from dotenv import load_dotenv
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from src.api.entities_api.dependencies import get_redis
from src.api.entities_api.orchestration.engine.orchestrator_core import \
    OrchestratorCore
from src.api.entities_api.orchestration.mixins.providers import _ProviderMixins
from src.api.entities_api.orchestration.streaming.hyperbolic import \
    HyperbolicDeltaNormalizer

load_dotenv()
LOG = LoggingUtility()


class QwenBaseWorker(_ProviderMixins, OrchestratorCore, ABC):
    """
    Qwen 2.5 Provider.
    Refactored for Event-Driven Tool Handoff (Smart Events).
    """

    def __init__(
        self, *, assistant_id=None, thread_id=None, redis=None, **extra
    ) -> None:
        self._assistant_cache = extra.get("assistant_cache") or {}
        self.redis = redis or get_redis()
        self.assistant_id = assistant_id
        self.thread_id = thread_id
        self.base_url = os.getenv("BASE_URL")
        self.api_key = extra.get("api_key")
        self.model_name = extra.get("model_name", "Qwen/Qwen2.5-VL-7B-Instruct")
        self.max_context_window = extra.get("max_context_window", 128000)
        self.threshold_percentage = extra.get("threshold_percentage", 0.8)

        # [NEW] State Handover for Tools
        self._pending_tool_payload: Optional[Dict[str, Any]] = None

        self.setup_services()
        LOG.debug("Qwen provider ready (assistant=%s)", assistant_id)

    @abstractmethod
    def _get_client_instance(self, api_key: str):
        pass

    # --------------------------------------------------------------------------
    # 1. STREAM PHASE: Suppress Raw Tools, Accumulate, Prepare Handover
    # --------------------------------------------------------------------------
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

        # Reset state
        self._pending_tool_payload = None
        api_key = api_key or self.api_key

        accumulated_content: str = ""
        # Buffers for Qwen JSON parts
        tool_args_buffer: str = ""
        tool_name_buffer: str = ""
        is_tool_call = False

        try:
            if mapped := self._get_model_map(model):
                model = mapped

            ctx = self._set_up_context_window(assistant_id, thread_id, trunk=True)

            payload = {
                "model": model,
                "messages": ctx,
                "max_tokens": 10000,
                "temperature": kwargs.get("temperature", 0.6),
                "stream": True,
            }

            # Start Status
            start_chunk = {"type": "status", "status": "started", "run_id": run_id}
            yield json.dumps(start_chunk)
            self._shunt_to_redis_stream(redis, stream_key, start_chunk)

            client = self._get_client_instance(api_key=api_key)
            # Using your existing execution wrapper
            raw_stream = self._execute_stream_request(client, payload)

            for chunk in HyperbolicDeltaNormalizer.iter_deltas(raw_stream, run_id):
                if stop_event.is_set():
                    break

                ctype, ccontent = chunk["type"], chunk["content"]

                # --- 1. ACCUMULATION & SUPPRESSION ---
                # We accumulate arguments but DO NOT yield them to client
                # This prevents the legacy SDK logic from firing prematurely
                if ctype == "call_arguments":
                    tool_args_buffer += ccontent
                    is_tool_call = True
                    continue

                if ctype == "tool_name":
                    tool_name_buffer += ccontent
                    is_tool_call = True
                    continue

                if ctype == "content":
                    accumulated_content += ccontent

                # Yield standard content
                yield json.dumps(chunk)
                self._shunt_to_redis_stream(redis, stream_key, chunk)

            # --- 2. PERSISTENCE PREP ---
            message_to_save = accumulated_content

            # Check if we captured a tool call
            if is_tool_call:
                try:
                    # Parse the accumulated buffers
                    # Handle case where name might be in the args or separate
                    final_tool_name = (
                        tool_name_buffer if tool_name_buffer else "unknown_tool"
                    )

                    if tool_args_buffer:
                        final_args = json.loads(tool_args_buffer)
                    else:
                        final_args = {}

                    payload_dict = {"name": final_tool_name, "arguments": final_args}

                    # Save clean JSON for history
                    message_to_save = json.dumps(payload_dict)

                    # [CRITICAL] Store payload for Handover
                    self._pending_tool_payload = payload_dict

                except Exception as e:
                    LOG.error(f"Error parsing Qwen tool args: {e}")
                    # Fallback to save raw data so we don't lose it
                    message_to_save = (
                        f"Tool: {tool_name_buffer} Args: {tool_args_buffer}"
                    )

            # Set the Function Call State on the Base Worker (Important!)
            self.parse_and_set_function_calls(message_to_save, accumulated_content)

            if message_to_save:
                self.finalize_conversation(
                    message_to_save, thread_id, assistant_id, run_id
                )

            # --- 3. STATUS SIGNAL ---
            if self._pending_tool_payload:
                self.project_david_client.runs.update_run_status(
                    run_id, StatusEnum.pending_action.value
                )
                yield json.dumps(
                    {"type": "status", "status": "processing", "run_id": run_id}
                )
            else:
                self.project_david_client.runs.update_run_status(
                    run_id, StatusEnum.completed.value
                )
                yield json.dumps(
                    {"type": "status", "status": "complete", "run_id": run_id}
                )

        except Exception as exc:
            err = {"type": "error", "content": str(exc)}
            yield json.dumps(err)
            self._shunt_to_redis_stream(redis, stream_key, err)
        finally:
            stop_event.set()

    # --------------------------------------------------------------------------
    # 2. TOOL PROCESSOR (Yields Manifest -> Polls)
    # --------------------------------------------------------------------------
    def _process_tool_calls(
        self,
        thread_id: str,
        assistant_id: str,
        content: Dict[str, Any],
        run_id: str,
        *,
        tool_call_id: Optional[str] = None,
        api_key: Optional[str] = None,
        poll_interval: float = 1.0,
        max_wait: float = 60.0,
    ) -> Generator[str, None, None]:

        # A. Create Action
        action = self.project_david_client.actions.create_action(
            tool_name=content["name"],
            run_id=run_id,
            tool_call_id=tool_call_id,
            function_args=content["arguments"],
        )

        # B. Yield Manifest (The Fix for your Error)
        # This gives the SDK the Action ID immediately.
        manifest = {
            "type": "tool_call_manifest",
            "run_id": run_id,
            "action_id": action.id,
            "tool": content["name"],
            "args": content["arguments"],
        }
        yield json.dumps(manifest)

        try:
            # C. Update & Poll
            self.project_david_client.runs.update_run_status(
                run_id, StatusEnum.pending_action.value
            )

            self._poll_for_completion(run_id, action.id, max_wait, poll_interval)

            LOG.debug("Tool %s processed (run %s)", content["name"], run_id)
            yield json.dumps(
                {"type": "status", "status": "tool_output_received", "run_id": run_id}
            )

        except Exception as exc:
            self._handle_tool_error(
                exc, thread_id=thread_id, assistant_id=assistant_id, action=action
            )
            yield json.dumps({"type": "error", "error": str(exc), "run_id": run_id})

    # --------------------------------------------------------------------------
    # 3. ORCHESTRATOR
    # --------------------------------------------------------------------------
    def process_conversation(
        self,
        thread_id,
        message_id,
        run_id,
        assistant_id,
        model,
        api_key=None,
        stream_reasoning=False,
        **kwargs,
    ):
        # Phase 1: Inference & Accumulation
        yield from self.stream(
            thread_id,
            message_id,
            run_id,
            assistant_id,
            model,
            api_key=api_key,
            **kwargs,
        )

        # Phase 2: Check Handover & Execute
        if self.get_function_call_state() and self._pending_tool_payload:
            yield from self._process_tool_calls(
                thread_id=thread_id,
                run_id=run_id,
                assistant_id=assistant_id,
                content=self._pending_tool_payload,
                api_key=api_key,
            )

            self.set_tool_response_state(False)
            self.set_function_call_state(None)
            self._pending_tool_payload = None

            # Phase 3: Final Response
            yield from self.stream(
                thread_id, None, run_id, assistant_id, model, api_key=api_key, **kwargs
            )
