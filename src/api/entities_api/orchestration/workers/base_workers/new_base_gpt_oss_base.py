from __future__ import annotations

import json
import os
import uuid
from abc import ABC, abstractmethod
from typing import Any, Generator, Optional

from dotenv import load_dotenv
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from src.api.entities_api.dependencies import get_redis
from src.api.entities_api.orchestration.engine.orchestrator_core import \
    OrchestratorCore
# --- DIRECT IMPORTS ---
from src.api.entities_api.orchestration.mixins.assistant_cache_mixin import \
    AssistantCacheMixin
from src.api.entities_api.orchestration.mixins.code_execution_mixin import \
    CodeExecutionMixin
from src.api.entities_api.orchestration.mixins.consumer_tool_handlers_mixin import \
    ConsumerToolHandlersMixin
from src.api.entities_api.orchestration.mixins.conversation_context_mixin import \
    ConversationContextMixin
from src.api.entities_api.orchestration.mixins.file_search_mixin import \
    FileSearchMixin
from src.api.entities_api.orchestration.mixins.json_utils_mixin import \
    JsonUtilsMixin
from src.api.entities_api.orchestration.mixins.platform_tool_handlers_mixin import \
    PlatformToolHandlersMixin
from src.api.entities_api.orchestration.mixins.shell_execution_mixin import \
    ShellExecutionMixin
from src.api.entities_api.orchestration.mixins.tool_routing_mixin import \
    ToolRoutingMixin
from src.api.entities_api.orchestration.streaming.hyperbolic import \
    HyperbolicDeltaNormalizer
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
    Abstract Base for openai/gpt-oss-120b Providers.
    Encapsulates core logic for tool normalization, streaming, and history preservation.
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
                if (
                    isinstance(parsed, dict)
                    and "name" in parsed
                    and "arguments" in parsed
                ):
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
        """Return the specific provider client."""
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
        force_refresh: bool = False,
        stream_reasoning: bool = False,
        api_key: Optional[str] = None,
        **kwargs,
    ) -> Generator[str, None, None]:
        redis = get_redis()
        stream_key = f"stream:{run_id}"
        stop_event = self.start_cancellation_monitor(run_id)

        # Reset state at start of stream
        self._current_tool_call_id = None

        # --- FIX: Initialize variables before try block to prevent UnboundLocalError ---
        current_tool_name: str | None = None
        current_tool_args_buffer: str = ""
        accumulated: str = ""
        assistant_reply: str = ""
        reasoning_reply: str = ""
        # -----------------------------------------------------------------------------

        try:
            if isinstance(model, str) and model.startswith("hyperbolic/"):
                model = model.replace("hyperbolic/", "")
            if mapped := self._get_model_map(model):
                model = mapped

            raw_ctx = self._set_up_context_window(
                assistant_id,
                thread_id,
                trunk=True,
                structured_tool_call=True,
                force_refresh=force_refresh,
            )

            cleaned_ctx, extracted_tools = self.prepare_native_tool_context(raw_ctx)

            if not api_key:
                yield json.dumps(
                    {"type": "error", "content": "Missing Hyperbolic API key."}
                )
                return

            client = self._get_client_instance(api_key=api_key)

            payload = {
                "messages": cleaned_ctx,
                "model": model,
                "tools": extracted_tools,
                "temperature": kwargs.get("temperature", 0.4),
                "top_p": 0.9,
            }

            LOG.info(
                f"DEBUG: stream_reasoning value: {stream_reasoning} | type: {type(stream_reasoning)}"
            )

            if stream_reasoning:
                del payload["tools"]

            raw_stream = client.stream_chat_completion(**payload)

            yield json.dumps({"type": "status", "status": "started", "run_id": run_id})

            token_iterator = async_to_sync_stream(raw_stream)

            for chunk in HyperbolicDeltaNormalizer.iter_deltas(token_iterator, run_id):
                if stop_event.is_set():
                    break

                ctype, ccontent = chunk["type"], chunk["content"]

                if ctype == "reasoning":
                    reasoning_reply += ccontent
                    yield json.dumps(chunk)
                    self._shunt_to_redis_stream(redis, stream_key, chunk)
                    continue

                elif ctype == "tool_name":
                    current_tool_name = ccontent

                elif ctype == "tool_call":
                    # Final full object received (safety catch)
                    current_tool_name = ccontent.get("name")
                    args = ccontent.get("arguments", "")
                    current_tool_args_buffer = (
                        json.dumps(args) if isinstance(args, dict) else str(args)
                    )

                elif ctype == "call_arguments":
                    # Simply accumulate arguments.
                    # No hot code extraction here - it happens later during execution.
                    current_tool_args_buffer += ccontent

                elif ctype == "content":
                    assistant_reply += ccontent
                    # Simply yield content.
                    # No code interpreter regex parsing here.
                    yield json.dumps(chunk)
                    self._shunt_to_redis_stream(redis, stream_key, chunk)

        except Exception as exc:
            err = {"type": "error", "content": f"GPT-OSS stream error: {exc}"}
            yield json.dumps(err)
            self._shunt_to_redis_stream(redis, stream_key, err)
        finally:
            # 1. Native Tool Finalization
            if current_tool_name:
                accumulated = json.dumps(
                    {"name": current_tool_name, "arguments": current_tool_args_buffer}
                )
            # 2. Manual <fc> Finalization (Safe Fallback for Llama 3.3 Prompting)
            elif (
                current_tool_args_buffer
                and current_tool_args_buffer.strip().startswith("{")
            ):
                accumulated = current_tool_args_buffer

            stop_event.set()

        yield json.dumps({"type": "status", "status": "complete", "run_id": run_id})

        # ------------------------------------------------------------------
        # 🔒 NORMALIZED PERSISTENCE PATH
        # ------------------------------------------------------------------
        normalized_fc_str = self._normalize_native_tool_payload(accumulated)

        has_fc = self.parse_and_set_function_calls(
            normalized_fc_str if normalized_fc_str else accumulated, assistant_reply
        )

        message_to_save = assistant_reply

        if has_fc:
            try:
                payload_dict = json.loads(normalized_fc_str)
                call_id = f"call_{uuid.uuid4().hex[:8]}"
                self._current_tool_call_id = call_id

                args_content = payload_dict.get("arguments", {})
                args_str = (
                    json.dumps(args_content)
                    if isinstance(args_content, dict)
                    else str(args_content)
                )

                tool_calls_structure = [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": payload_dict.get("name"),
                            "arguments": args_str,
                        },
                    }
                ]
                message_to_save = json.dumps(tool_calls_structure)
            except Exception as e:
                LOG.error(f"Error structuring tool calls for persistence: {e}")
                message_to_save = normalized_fc_str

        if message_to_save:
            self.finalize_conversation(message_to_save, thread_id, assistant_id, run_id)

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

        yield from self.stream(
            thread_id,
            message_id,
            run_id,
            assistant_id,
            model,
            api_key=api_key,
            **kwargs,
        )

        has_tools = False
        if hasattr(self, "get_function_call_state"):
            has_tools = self.get_function_call_state()

        if has_tools:
            # Retrieve the ID generated inside stream()
            tool_call_id = getattr(self, "_current_tool_call_id", None)

            # --------------------------------------------------------------
            #  Tool calls dealt with here
            #  - Yields any interleaving chunks from function call handler
            # -----------------------------------------------------------
            yield from self.process_tool_calls(
                thread_id,
                run_id,
                assistant_id,
                tool_call_id=tool_call_id,  # Pass it down
                model=model,
                api_key=api_key,
            )

            if hasattr(self, "set_tool_response_state"):
                self.set_tool_response_state(False)
            if hasattr(self, "set_function_call_state"):
                self.set_function_call_state(None)

            # Reset ID
            self._current_tool_call_id = None

            self._force_refresh = True

            # -----------------------------------
            # Turn 2 after a tool is triggered
            # - Force the redis cache to refresh
            # ------------------------------------
            yield from self.stream(
                thread_id,
                None,
                run_id,
                assistant_id,
                model,
                force_refresh=True,
                api_key=api_key,
                **kwargs,
            )
