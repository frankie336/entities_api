# src/api/entities_api/orchestration/workers/base_workers/new_base_gpt_oss_base.py
from __future__ import annotations

import json
import os
import uuid
from abc import ABC, abstractmethod
from typing import Any, Generator, Optional

from dotenv import load_dotenv
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from entities_api.orchestration.streaming.hyperbolic_async_client import AsyncHyperbolicClient
from src.api.entities_api.dependencies import get_redis
from src.api.entities_api.orchestration.engine.orchestrator_core import OrchestratorCore

# --- DIRECT IMPORTS ---
from src.api.entities_api.orchestration.mixins.assistant_cache_mixin import AssistantCacheMixin
from src.api.entities_api.orchestration.mixins.code_execution_mixin import CodeExecutionMixin
from src.api.entities_api.orchestration.mixins.consumer_tool_handlers_mixin import (
    ConsumerToolHandlersMixin,
)
from src.api.entities_api.orchestration.mixins.conversation_context_mixin import (
    ConversationContextMixin,
)
from src.api.entities_api.orchestration.mixins.file_search_mixin import FileSearchMixin
from src.api.entities_api.orchestration.mixins.json_utils_mixin import JsonUtilsMixin
from src.api.entities_api.orchestration.mixins.platform_tool_handlers_mixin import (
    PlatformToolHandlersMixin,
)
from src.api.entities_api.orchestration.mixins.shell_execution_mixin import ShellExecutionMixin
from src.api.entities_api.orchestration.mixins.tool_routing_mixin import ToolRoutingMixin
from src.api.entities_api.orchestration.streaming.hyperbolic import HyperbolicDeltaNormalizer
from src.api.entities_api.utils.async_to_sync import async_to_sync_stream

load_dotenv()
LOG = LoggingUtility()


class _ProviderMixins(
    AssistantCacheMixin,
    JsonUtilsMixin,
    ConversationContextMixin,
    ToolRoutingMixin,
    PlatformToolHandlersMixin,
    ConsumerToolHandlersMixin,
    CodeExecutionMixin,
    ShellExecutionMixin,
    FileSearchMixin,
):
    """Flat bundle for Hyperbolic GPT-OSS Provider."""


class GptOssBaseWorker(_ProviderMixins, OrchestratorCore, ABC):
    """
    Specialized Provider for openai/gpt-oss-120b.
    """

    def __init__(
        self,
        *,
        assistant_id: str | None = None,
        thread_id: str | None = None,
        redis=None,
        base_url: str | None = None,
        api_key: str | None = None,
        assistant_cache: dict | None = None,
        **extra,
    ) -> None:
        self._assistant_cache: dict = assistant_cache or extra.get("assistant_cache") or {}
        self.redis = redis or get_redis()
        self.assistant_id = assistant_id
        self.thread_id = thread_id
        self.base_url = base_url or os.getenv("BASE_URL")
        self.api_key = api_key

        # Model Specs
        self.model_name = extra.get("model_name", "openai/gpt-oss-120b")
        self.max_context_window = extra.get("max_context_window", 131072)
        self.threshold_percentage = extra.get("threshold_percentage", 0.8)

        # State for Dialogue Binding
        self._current_tool_call_id: str | None = None

        self.setup_services()

        # Runtime Safety
        if not hasattr(self, "get_function_call_state"):
            LOG.error("CRITICAL: ToolRoutingMixin failed to load. Monkey-patching.")
            self.get_function_call_state = lambda: None
            self.set_function_call_state = lambda x: None
            self.set_tool_response_state = lambda x: None

        LOG.debug("Hyperbolic-GptOss provider ready (assistant=%s)", assistant_id)

    # ------------------------------------------------------------------
    # NORMALIZATION FIX
    # ------------------------------------------------------------------
    def _normalize_native_tool_payload(self, accumulated: str | None) -> str | None:
        if not accumulated:
            return None
        try:
            payload = json.loads(accumulated)
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None

        name = payload.get("name")
        args = payload.get("arguments")
        if not name or args is None:
            return None

        if isinstance(args, str):
            try:
                parsed = json.loads(args)
                if isinstance(parsed, dict) and "name" in parsed and "arguments" in parsed:
                    args = parsed["arguments"]
                else:
                    args = parsed
            except Exception:
                pass

        if not isinstance(args, dict):
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except:
                    pass
            if not isinstance(args, dict):
                return None

        canonical = {"name": name, "arguments": args}
        return json.dumps(canonical)

    @abstractmethod
    def _get_client_instance(self, api_key: str):
        """Subclasses must implement specific provider client creation."""
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

        assistant_reply = ""
        accumulated = ""

        try:
            # 1. Clean Model ID for API
            if isinstance(model, str) and model.startswith("hyperbolic/"):
                model = model.replace("hyperbolic/", "")
            if mapped := self._get_model_map(model):
                model = mapped

            # 2. Context Window & Tool Preparation
            raw_ctx = self._set_up_context_window(
                assistant_id, thread_id, trunk=True, structured_tool_call=True
            )
            cleaned_ctx, extracted_tools = self.prepare_native_tool_context(raw_ctx)

            if not api_key:
                yield json.dumps({"type": "error", "content": "Missing Hyperbolic API key."})
                return

            payload = {
                "model": model,
                "messages": cleaned_ctx,
                "tools": extracted_tools,
                "max_tokens": 10000,
                "temperature": kwargs.get("temperature", 0.4),
            }

            start_chunk = {"type": "status", "status": "started", "run_id": run_id}
            yield json.dumps(start_chunk)
            self._shunt_to_redis_stream(redis, stream_key, start_chunk)

            # -----------------------------------------------------------
            # DYNAMIC CLIENT INJECTION
            # -----------------------------------------------------------
            client = self._get_client_instance(api_key=api_key)
            raw_stream = client.chat.completions.create(**payload)
            # -----------------------------------------------------------

            # 3. Requesting Stream

            yield json.dumps({"type": "status", "status": "started", "run_id": run_id})

            assistant_reply, accumulated, reasoning_reply = "", "", ""
            code_mode = False

            token_iterator = async_to_sync_stream(raw_stream)

            # 4. Standardized Processing via Universal Normalizer
            for chunk in HyperbolicDeltaNormalizer.iter_deltas(token_iterator, run_id):
                if stop_event.is_set():
                    break

                ctype, ccontent = chunk["type"], chunk["content"]

                # --- METHODOLOGY: ACCUMULATION (No Tag Wrapping) ---

                if ctype == "content":
                    assistant_reply += ccontent

                elif ctype == "call_arguments":
                    # Accumulate raw function args (JSON) directly into history/accumulator
                    # without <fc> tags, per user request.
                    accumulated += ccontent

                elif ctype == "reasoning":
                    # Reasoning is passed to stream, but NOT added to accumulated/history.
                    reasoning_reply += ccontent

                # --- CODE INTERPRETER INTERLEAVING ---
                if ctype == "content":
                    parse_ci = getattr(self, "parse_code_interpreter_partial", None)
                    ci_match = parse_ci(assistant_reply) if parse_ci and not code_mode else None

                    if ci_match:
                        code_mode = True
                        start = {"type": "hot_code", "content": "```python\n"}
                        yield json.dumps(start)
                        self._shunt_to_redis_stream(redis, stream_key, start)

                        if hasattr(self, "_process_code_interpreter_chunks"):
                            res, _ = self._process_code_interpreter_chunks(
                                "", ci_match.get("code", "")
                            )
                            for r in res:
                                yield r
                                self._shunt_to_redis_stream(redis, stream_key, json.loads(r))
                        continue

                    if code_mode:
                        if hasattr(self, "_process_code_interpreter_chunks"):
                            res, code_buf = self._process_code_interpreter_chunks(ccontent, "")
                            for r in res:
                                yield r
                                self._shunt_to_redis_stream(redis, stream_key, json.loads(r))
                        else:
                            yield json.dumps({"type": "hot_code", "content": ccontent})
                        continue

                # Yield the standardized chunk to frontend
                yield json.dumps(chunk)
                self._shunt_to_redis_stream(redis, stream_key, chunk)

        except Exception as exc:
            err = {"type": "error", "content": f"GPT-OSS stream error: {exc}"}
            yield json.dumps(err)
            self._shunt_to_redis_stream(redis, stream_key, err)
        finally:
            stop_event.set()

        # 5. FINAL CLOSE-OUT & SMART HISTORY PRESERVATION
        yield json.dumps({"type": "status", "status": "complete", "run_id": run_id})

        # Check for function calls first to determine what to save
        has_fc = self.parse_and_set_function_calls(accumulated, assistant_reply)

        # Save 'accumulated' (raw JSON) if tool called, otherwise reply.
        # Ensure that downstream parser expects raw JSON if has_fc is True.
        message_to_save = accumulated if has_fc else assistant_reply

        if not message_to_save:
            message_to_save = assistant_reply

        if message_to_save:
            self.finalize_conversation(message_to_save, thread_id, assistant_id, run_id)

        # Logic for Stage 2 Function Call Triggering
        if has_fc:
            self.project_david_client.runs.update_run_status(
                run_id, StatusEnum.pending_action.value
            )
        else:
            self.project_david_client.runs.update_run_status(run_id, StatusEnum.completed.value)

    def process_conversation(
        self,
        thread_id: str,
        message_id: Optional[str],
        run_id: str,
        assistant_id: str,
        model: Any,
        api_key: Optional[str] = None,
        **kwargs,
    ):
        # 1. TURN 1: Initial Stream
        yield from self.stream(
            thread_id,
            message_id,
            run_id,
            assistant_id,
            model,
            api_key=api_key,
            **kwargs,
        )

        # 2. Check for Tool Calls (Aligning with Qwen logic)
        has_tools = False
        if hasattr(self, "get_function_call_state"):
            has_tools = self.get_function_call_state() is not None

        if has_tools:
            LOG.info(f"Orchestrator: Tool call detected for run {run_id}. Processing tools...")

            # Use the ID captured in stream(), but fallback to Mixin search if None
            tool_call_id = getattr(self, "_current_tool_call_id", None)

            # 3. Execute Tools (Yields the "Action" metadata to the UI)
            yield from self.process_tool_calls(
                thread_id,
                run_id,
                assistant_id,
                tool_call_id=tool_call_id,
                model=model,
                api_key=api_key,
            )

            # 4. Clean up state AFTER execution
            if hasattr(self, "set_tool_response_state"):
                self.set_tool_response_state(False)
            if hasattr(self, "set_function_call_state"):
                self.set_function_call_state(None)

            # Reset ID for the next potential turn
            self._current_tool_call_id = None

            # 5. TURN 2: Final Response
            LOG.info(f"Orchestrator: Tools executed. Starting Turn 2 for run {run_id}.")
            yield from self.stream(
                thread_id,
                None,
                run_id,
                assistant_id,
                model,
                force_refresh=True,  # Ensure it sees the tool result in the DB
                api_key=api_key,
                **kwargs,
            )

        # 6. FINAL STATUS UPDATE (Move this here, OUT of the stream method)
        # Only set completed if we aren't still in a tool loop
        final_has_tools = self.get_function_call_state() is not None
        if not final_has_tools:
            LOG.info(f"Orchestrator: Run {run_id} fully complete. Setting status.")
            self.project_david_client.runs.update_run_status(run_id, StatusEnum.completed.value)
