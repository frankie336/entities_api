from __future__ import annotations

import json
import os
from typing import Any, Generator, Optional

from dotenv import load_dotenv
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from src.api.entities_api.dependencies import get_redis
from src.api.entities_api.orchestration.engine.orchestrator_core import \
    OrchestratorCore
from src.api.entities_api.orchestration.mixins import (
    AssistantCacheMixin, CodeExecutionMixin, ConsumerToolHandlersMixin,
    ConversationContextMixin, FileSearchMixin, JsonUtilsMixin,
    PlatformToolHandlersMixin, ShellExecutionMixin, ToolRoutingMixin)
from src.api.entities_api.orchestration.streaming.hyperbolic import \
    HyperbolicDeltaNormalizer
from src.api.entities_api.orchestration.streaming.hyperbolic_async_client import \
    AsyncHyperbolicClient
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


class HyperbolicGptOss(_ProviderMixins, OrchestratorCore):
    """
    Specialized Provider for openai/gpt-oss-120b.
    Standardizes 'Analysis' channels into 'reasoning' data types.
    Supports both Native Tool Calls and Channel-based tool outputs.
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
        self._assistant_cache: dict = (
            assistant_cache or extra.get("assistant_cache") or {}
        )
        self.redis = redis or get_redis()
        self.assistant_id = assistant_id
        self.thread_id = thread_id
        self.base_url = base_url or os.getenv("BASE_URL")
        self.api_key = api_key

        # Model Specs
        self.model_name = extra.get("model_name", "openai/gpt-oss-120b")
        self.max_context_window = extra.get("max_context_window", 131072)
        self.threshold_percentage = extra.get("threshold_percentage", 0.8)

        self.setup_services()
        LOG.debug("Hyperbolic-GptOss provider ready (assistant=%s)", assistant_id)

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

        try:
            # 1. Clean Model ID for API
            if isinstance(model, str) and model.startswith("hyperbolic/"):
                model = model.replace("hyperbolic/", "")
            if mapped := self._get_model_map(model):
                model = mapped

            # 2. Context Window & Tool Preparation
            raw_ctx = self._set_up_context_window(
                assistant_id, thread_id, trunk=True, tools_native=True
            )
            cleaned_ctx, extracted_tools = self.prepare_native_tool_context(raw_ctx)

            if not api_key:
                yield json.dumps(
                    {"type": "error", "content": "Missing Hyperbolic API key."}
                )
                return

            client = AsyncHyperbolicClient(
                api_key=api_key, base_url=os.getenv("HYPERBOLIC_BASE_URL")
            )

            # 3. Requesting Stream
            async_stream = client.stream_chat_completion(
                messages=cleaned_ctx,
                tools=extracted_tools,
                model=model,
                temperature=kwargs.get("temperature", 0.4),
                top_p=0.9,
            )

            yield json.dumps({"type": "status", "status": "started", "run_id": run_id})

            assistant_reply, accumulated, reasoning_reply = "", "", ""
            code_mode = False

            # Helper for constructing JSON string manually in 'accumulated'
            is_native_tool_call = False
            current_native_tool_call = {}

            token_iterator = async_to_sync_stream(async_stream)

            # 4. Standardized Processing via Universal Normalizer
            for chunk in HyperbolicDeltaNormalizer.iter_deltas(token_iterator, run_id):
                if stop_event.is_set():
                    break

                ctype, ccontent = chunk["type"], chunk["content"]

                # --- METHODOLOGY: ACCUMULATION (No Tag Wrapping) ---

                if ctype == "content":
                    assistant_reply += ccontent

                elif ctype == "tool_name":
                    # Native Tool Call Start detected (from Llama/GPT-OSS native)
                    is_native_tool_call = True
                    current_native_tool_call = {"name": ccontent, "arguments": ""}
                    # Start constructing standard JSON in history
                    accumulated += f'{{"name": "{ccontent}", "arguments": '

                elif ctype == "call_arguments":
                    # Append raw JSON arguments to history
                    if is_native_tool_call:
                        current_native_tool_call["arguments"] += ccontent
                    # If channel-based (no tool_name event), this just appends the raw JSON
                    accumulated += ccontent

                elif ctype == "reasoning":
                    # Reasoning is passed to stream, but NOT added to accumulated/history.
                    reasoning_reply += ccontent

                # --- CODE INTERPRETER INTERLEAVING ---
                if ctype == "content":
                    parse_ci = getattr(self, "parse_code_interpreter_partial", None)
                    ci_match = (
                        parse_ci(assistant_reply)
                        if parse_ci and not code_mode
                        else None
                    )

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
                                self._shunt_to_redis_stream(
                                    redis, stream_key, json.loads(r)
                                )
                        continue

                    if code_mode:
                        if hasattr(self, "_process_code_interpreter_chunks"):
                            res, code_buf = self._process_code_interpreter_chunks(
                                ccontent, ""
                            )
                            for r in res:
                                yield r
                                self._shunt_to_redis_stream(
                                    redis, stream_key, json.loads(r)
                                )
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
            # Ensure JSON is valid in history if tool call was native
            if is_native_tool_call and accumulated:
                stripped = accumulated.strip()
                if not stripped.endswith("}"):
                    accumulated += "}"
            stop_event.set()

        # 5. FINAL CLOSE-OUT & SMART HISTORY PRESERVATION
        yield json.dumps({"type": "status", "status": "complete", "run_id": run_id})

        # Check for function calls first to determine what to save
        has_fc = self.parse_and_set_function_calls(accumulated, assistant_reply)

        # Save 'accumulated' (raw JSON) if tool called, otherwise reply.
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
            self.project_david_client.runs.update_run_status(
                run_id, StatusEnum.completed.value
            )

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
        # Pass 1: Initial Generation
        yield from self.stream(
            thread_id,
            message_id,
            run_id,
            assistant_id,
            model,
            api_key=api_key,
            **kwargs,
        )

        # Pass 2: Tool Execution (ReAct Loop)
        if self.get_function_call_state():
            yield from self.process_function_calls(
                thread_id, run_id, assistant_id, model=model, api_key=api_key
            )
            self.set_tool_response_state(False)
            self.set_function_call_state(None)

            # Follow-up with tool results
            yield from self.stream(
                thread_id, None, run_id, assistant_id, model, api_key=api_key, **kwargs
            )
