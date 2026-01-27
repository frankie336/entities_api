from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from typing import Any, Generator, Optional

from dotenv import load_dotenv
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from src.api.entities_api.dependencies import get_redis
from src.api.entities_api.orchestration.engine.orchestrator_core import \
    OrchestratorCore
# --- RESTORED DIRECT MIXIN IMPORTS ---
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

load_dotenv()
LOG = LoggingUtility()


# --- RESTORED LOCAL MIXIN BUNDLE ---
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
    """Flat bundle for GPT-OSS Provider Mixins."""


class GptOssBaseWorker(_ProviderMixins, OrchestratorCore, ABC):
    """
    Abstract Base for openai/gpt-oss-120b Providers.
    Encapsulates core logic for tool normalization, streaming, and history preservation.
    """

    def __init__(
        self, *, assistant_id=None, thread_id=None, redis=None, **extra
    ) -> None:
        self._assistant_cache = extra.get("assistant_cache") or {}
        self.redis = redis or get_redis()
        self.assistant_id = assistant_id
        self.thread_id = thread_id
        self.api_key = extra.get("api_key")

        # Model Specs
        self.model_name = extra.get("model_name", "openai/gpt-oss-120b")
        self.max_context_window = extra.get("max_context_window", 131072)
        self.threshold_percentage = extra.get("threshold_percentage", 0.8)

        # State for Dialogue Binding
        self._current_tool_call_id: str | None = None

        self.setup_services()

        # Runtime Safety Check (Should pass now)
        if not hasattr(self, "get_function_call_state"):
            LOG.error("CRITICAL: ToolRoutingMixin failed to load. Monkey-patching.")
            self.get_function_call_state = lambda: None
            self.set_function_call_state = lambda x: None
            self.set_tool_response_state = lambda x: None

        LOG.debug(f"{self.__class__.__name__} ready (assistant={assistant_id})")

    @abstractmethod
    def _get_client_instance(self, api_key: str):
        """Return the specific provider client."""
        pass

    @abstractmethod
    def _execute_stream_request(self, client, payload: dict) -> Any:
        """Execute request (Sync or Async-to-Sync)."""
        pass

    @property
    def assistant_cache(self) -> dict:
        return self._assistant_cache

    @assistant_cache.setter
    def assistant_cache(self, value: dict) -> None:
        self._assistant_cache = value

    def get_assistant_cache(self) -> dict:
        return self._assistant_cache

    def _normalize_native_tool_payload(self, accumulated: str | None) -> str | None:
        """Standardizes tool call JSON structure."""
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

        # Recursively unwrap nested stringified JSON args
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

        # Use instance key if not provided
        api_key = api_key or self.api_key
        self._current_tool_call_id = None

        try:
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
                yield json.dumps({"type": "error", "content": "Missing API key."})
                return

            client = self._get_client_instance(api_key=api_key)

            payload = {
                "messages": cleaned_ctx,
                "model": model,
                "tools": extracted_tools,
                "temperature": kwargs.get("temperature", 0.4),
                "top_p": 0.9,
            }

            if stream_reasoning:
                del payload["tools"]

            # Abstracted Execution (Sync vs Async-Wrapper)
            raw_stream = self._execute_stream_request(client, payload)

            yield json.dumps({"type": "status", "status": "started", "run_id": run_id})

            # State Tracking
            assistant_reply = ""
            reasoning_reply = ""
            current_tool_name = None
            current_tool_args_buffer = ""
            accumulated = ""

            for chunk in HyperbolicDeltaNormalizer.iter_deltas(raw_stream, run_id):
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
                    # Final full object (Legacy/Fallback)
                    current_tool_name = ccontent.get("name")
                    args = ccontent.get("arguments", "")
                    current_tool_args_buffer = (
                        json.dumps(args) if isinstance(args, dict) else str(args)
                    )

                elif ctype == "call_arguments":
                    current_tool_args_buffer += ccontent

                elif ctype == "content":
                    assistant_reply += ccontent
                    yield json.dumps(chunk)
                    self._shunt_to_redis_stream(redis, stream_key, chunk)

        except Exception as exc:
            err = {"type": "error", "content": f"Stream Error: {exc}"}
            yield json.dumps(err)
            self._shunt_to_redis_stream(redis, stream_key, err)
        finally:
            if current_tool_name:
                accumulated = json.dumps(
                    {"name": current_tool_name, "arguments": current_tool_args_buffer}
                )
            elif (
                current_tool_args_buffer
                and current_tool_args_buffer.strip().startswith("{")
            ):
                accumulated = current_tool_args_buffer
            stop_event.set()

        yield json.dumps({"type": "status", "status": "complete", "run_id": run_id})

        # --- Persistence ---
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
                LOG.error(f"Error structuring tool calls: {e}")
                message_to_save = normalized_fc_str

        if message_to_save:
            self.finalize_conversation(message_to_save, thread_id, assistant_id, run_id)

        status = (
            StatusEnum.pending_action.value if has_fc else StatusEnum.completed.value
        )
        self.project_david_client.runs.update_run_status(run_id, status)

    def process_conversation(
        self, thread_id, message_id, run_id, assistant_id, model, api_key=None, **kwargs
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

        # This will now work correctly because ToolRoutingMixin is guaranteed to be present
        if self.get_function_call_state():
            tool_call_id = getattr(self, "_current_tool_call_id", None)
            yield from self.process_tool_calls(
                thread_id,
                run_id,
                assistant_id,
                tool_call_id=tool_call_id,
                model=model,
                api_key=api_key,
            )
            self.set_tool_response_state(False)
            self.set_function_call_state(None)
            self._current_tool_call_id = None

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
