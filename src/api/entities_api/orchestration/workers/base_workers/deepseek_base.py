from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Generator, Optional

from dotenv import load_dotenv
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from entities_api.orchestration.mixins import (AssistantCacheMixin,
                                               CodeExecutionMixin,
                                               ConsumerToolHandlersMixin,
                                               ConversationContextMixin,
                                               FileSearchMixin, JsonUtilsMixin,
                                               PlatformToolHandlersMixin,
                                               ShellExecutionMixin,
                                               ToolRoutingMixin)
from src.api.entities_api.dependencies import get_redis
from src.api.entities_api.orchestration.engine.orchestrator_core import \
    OrchestratorCore
from src.api.entities_api.orchestration.streaming.hyperbolic import \
    HyperbolicDeltaNormalizer

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
    """Flat bundle for Provider Mixins."""


class DeepSeekBaseWorker(_ProviderMixins, OrchestratorCore, ABC):
    """
    Refactored DeepSeekBaseWorker.
    Reconciles Tag Injection with Structured Persistence and Tool ID tracking.
    """

    def __init__(
        self, *, assistant_id=None, thread_id=None, redis=None, **extra
    ) -> None:
        # ... (existing init logic) ...
        self._current_tool_call_id: str | None = None  # Track ID for Turn 2
        super().__init__(
            assistant_id=assistant_id, thread_id=thread_id, redis=redis, **extra
        )

    # ------------------------------------------------------------------
    # ADDED: Normalization Helper for Robust JSON Parsing
    # ------------------------------------------------------------------
    def _normalize_native_tool_payload(self, accumulated: str | None) -> str | None:
        if not accumulated:
            return None
        # Remove tags if present
        clean = accumulated.replace("<fc>", "").replace("</fc>", "").strip()
        try:
            payload = json.loads(clean)
            if not isinstance(payload, dict):
                return None
            name = payload.get("name")
            args = payload.get("arguments")
            if not name or args is None:
                return None
            # Handle recursive stringified JSON in arguments
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except:
                    pass
            return json.dumps({"name": name, "arguments": args})
        except:
            return None

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
        api_key = api_key or self.api_key

        # Reset ID for new stream
        self._current_tool_call_id = None

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

            client = self._get_client_instance(api_key=api_key)
            raw_stream = client.chat.completions.create(**payload)

            yield json.dumps({"type": "status", "status": "started", "run_id": run_id})

            assistant_reply, accumulated, reasoning_reply = "", "", ""
            current_block = None

            for chunk in HyperbolicDeltaNormalizer.iter_deltas(raw_stream, run_id):
                if stop_event.is_set():
                    break

                ctype, ccontent = chunk["type"], chunk["content"]

                # 1. TAG INJECTION
                if ctype == "content":
                    if current_block == "fc":
                        accumulated += "</fc>"
                    elif current_block == "think":
                        accumulated += "</think>"
                    current_block = None
                    assistant_reply += ccontent

                elif ctype in ["tool_name", "call_arguments", "tool_call"]:
                    if current_block != "fc":
                        if current_block == "think":
                            accumulated += "</think>"
                        accumulated += "<fc>"
                        current_block = "fc"

                    # Capture the Provider's Tool ID if present
                    if ctype == "tool_call" and isinstance(ccontent, dict):
                        self._current_tool_call_id = ccontent.get("id")

                elif ctype == "reasoning":
                    if current_block != "think":
                        if current_block == "fc":
                            accumulated += "</fc>"
                        accumulated += "<think>"
                        current_block = "think"
                    reasoning_reply += ccontent

                accumulated += (
                    str(ccontent) if ctype != "tool_call" else json.dumps(ccontent)
                )
                yield json.dumps(chunk)
                self._shunt_to_redis_stream(redis, stream_key, chunk)

            if current_block == "fc":
                accumulated += "</fc>"
            elif current_block == "think":
                accumulated += "</think>"

            yield json.dumps({"type": "status", "status": "complete", "run_id": run_id})

            # 2. SMART HISTORY PRESERVATION
            has_fc = self.parse_and_set_function_calls(accumulated, assistant_reply)
            message_to_save = assistant_reply

            if has_fc:
                try:
                    # Use the normalization helper
                    normalized = self._normalize_native_tool_payload(accumulated)
                    if normalized:
                        payload_dict = json.loads(normalized)

                        # Use provider ID or fallback
                        if not self._current_tool_call_id:
                            self._current_tool_call_id = f"call_{uuid.uuid4().hex[:8]}"

                        # SAVE AS STRUCTURED ARRAY (Standard OpenAI format)
                        message_to_save = json.dumps(
                            [
                                {
                                    "id": self._current_tool_call_id,
                                    "type": "function",
                                    "function": {
                                        "name": payload_dict.get("name"),
                                        "arguments": json.dumps(
                                            payload_dict.get("arguments", {})
                                        ),
                                    },
                                }
                            ]
                        )
                except Exception as e:
                    LOG.error(f"Error structuring tool calls: {e}")
                    message_to_save = accumulated

            if message_to_save or reasoning_reply:
                self.finalize_conversation(
                    message_to_save, thread_id, assistant_id, run_id
                )

            # 3. CORRECT STATUS
            new_status = StatusEnum.pending_action if has_fc else StatusEnum.completed
            self.project_david_client.runs.update_run_status(run_id, new_status.value)

        except Exception as exc:
            yield json.dumps({"type": "error", "content": str(exc)})
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
        """Standard process loop, relies on self.stream implementation."""
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
