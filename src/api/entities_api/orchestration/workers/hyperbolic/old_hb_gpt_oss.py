from __future__ import annotations

import json
import os
import uuid
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


class HyperbolicGptOssWorker(_ProviderMixins, OrchestratorCore):
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

        # 1. Setup Context & Client
        api_key = api_key or self.api_key
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

        # --- ONE LINER DEBUG ---
        import json

        LOG.info(
            f"\n=== DEBUG CLEANED_CTX ({len(cleaned_ctx)} msgs) ===\n{json.dumps(cleaned_ctx, indent=2)}\n================================"
        )

        client = self._get_hyperbolic_client(
            api_key=api_key, base_url=os.getenv("HYPERBOLIC_BASE_URL")
        )

        payload = {
            "messages": cleaned_ctx,
            "model": model,
            "tools": extracted_tools,
            "tool_choice": "auto",
            "temperature": kwargs.get("temperature", 0.4),
        }
        if stream_reasoning:
            del payload["tools"]

        # 2. Initialize State Buffers (The Qwen Pattern)
        assistant_reply, accumulated, reasoning_reply = "", "", ""
        current_block = None  # Tracks if we are inside <think> or <fc>
        self._current_tool_call_id = None  # Reset ID

        try:
            async_stream = client.stream_chat_completion(**payload)
            token_iterator = async_to_sync_stream(async_stream)

            yield json.dumps({"type": "status", "status": "started", "run_id": run_id})

            # 3. Process Deltas with Tag Injection (Source of Truth for Mixins)
            for chunk in HyperbolicDeltaNormalizer.iter_deltas(token_iterator, run_id):
                if stop_event.is_set():
                    break

                ctype, ccontent = chunk["type"], chunk["content"]

                if ctype == "reasoning":
                    if current_block != "think":
                        if current_block == "fc":
                            accumulated += "</fc>"
                        accumulated += "<think>"
                        current_block = "think"
                    reasoning_reply += ccontent

                elif ctype in ["tool_name", "call_arguments", "tool_call"]:
                    if current_block != "fc":
                        if current_block == "think":
                            accumulated += "</think>"
                        accumulated += "<fc>"
                        current_block = "fc"

                    if ctype == "tool_call":
                        # CRITICAL: Preserve the ID from the provider if available
                        self._current_tool_call_id = ccontent.get("id")
                        ccontent = json.dumps(ccontent)

                elif ctype == "content":
                    if current_block == "fc":
                        accumulated += "</fc>"
                    elif current_block == "think":
                        accumulated += "</think>"
                    current_block = None
                    assistant_reply += ccontent

                # Accumulate into the string buffer that the Mixins will use
                accumulated += str(ccontent)

                # Yield immediately for UI
                yield json.dumps(chunk)
                self._shunt_to_redis_stream(redis, stream_key, chunk)

        except Exception as exc:
            LOG.error(f"Stream Error: {exc}")
            yield json.dumps({"type": "error", "content": str(exc)})
        finally:
            # 4. Close any dangling tags
            if current_block == "fc":
                accumulated += "</fc>"
            elif current_block == "think":
                accumulated += "</think>"
            stop_event.set()

        yield json.dumps({"type": "status", "status": "complete", "run_id": run_id})

        # 5. Smart History Preservation (Reconciling Tag Detection with Array Persistence)
        # Use the accumulated string (with tags) to trigger ToolRoutingMixin detection
        has_fc = self.parse_and_set_function_calls(accumulated, assistant_reply)
        message_to_save = assistant_reply

        if has_fc:
            try:
                # 5a. Clean tags before parsing JSON
                clean_json_str = (
                    accumulated.replace("<fc>", "").replace("</fc>", "").strip()
                )

                # 5b. Normalize to handle recursive arguments
                normalized = self._normalize_native_tool_payload(clean_json_str)
                payload_dict = json.loads(normalized)

                # 5c. Set up the ID (Use provider ID if we caught it, else generate)
                if not self._current_tool_call_id:
                    self._current_tool_call_id = f"call_{uuid.uuid4().hex[:8]}"

                # 5d. Prepare structured arguments string
                args_content = payload_dict.get("arguments", {})
                args_str = (
                    json.dumps(args_content)
                    if isinstance(args_content, dict)
                    else str(args_content)
                )

                # 5e. Build the GPT-OSS / OpenAI standard tool_calls array
                tool_calls_structure = [
                    {
                        "id": self._current_tool_call_id,
                        "type": "function",
                        "function": {
                            "name": payload_dict.get("name"),
                            "arguments": args_str,
                        },
                    }
                ]
                # Overwrite message_to_save with the JSON array
                message_to_save = json.dumps(tool_calls_structure)

            except Exception as e:
                LOG.error(f"Error structuring tool calls for persistence: {e}")
                # Fallback to accumulated text if parsing fails
                message_to_save = accumulated

        # 6. Finalize DB persistence
        if message_to_save or reasoning_reply:
            self.finalize_conversation(message_to_save, thread_id, assistant_id, run_id)

        # 7. Set Final Status
        new_status = StatusEnum.pending_action if has_fc else StatusEnum.completed
        self.project_david_client.runs.update_run_status(run_id, new_status.value)
        LOG.info(f"Run {run_id} finalized with status: {new_status.value}")

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
            LOG.info(
                f"Orchestrator: Tool call detected for run {run_id}. Processing tools..."
            )

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
            self.project_david_client.runs.update_run_status(
                run_id, StatusEnum.completed.value
            )
