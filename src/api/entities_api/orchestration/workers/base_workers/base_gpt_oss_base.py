from __future__ import annotations

import json
import os
import re
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
            self.get_function_call_state = lambda: False
            self.set_function_call_state = lambda x: None
            self.set_tool_response_state = lambda x: None

        LOG.debug("Hyperbolic-GptOss provider ready (assistant=%s)", assistant_id)

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

        self._current_tool_call_id = None
        assistant_reply = ""
        accumulated = ""
        reasoning_reply = ""
        current_block = None

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

            if stream_reasoning:
                del payload["tools"]

            raw_stream = client.stream_chat_completion(**payload)
            yield json.dumps({"type": "status", "status": "started", "run_id": run_id})

            token_iterator = async_to_sync_stream(raw_stream)

            # -----------------------------------------------------------
            # 1. PROCESS DELTAS & INJECT TAGS
            # -----------------------------------------------------------
            for chunk in HyperbolicDeltaNormalizer.iter_deltas(token_iterator, run_id):
                if stop_event.is_set():
                    break

                ctype, ccontent = chunk["type"], chunk["content"]

                # --- FILTERING FIX ---
                # Only process string content. Ignore dicts/lists (metadata) to prevent garbage injection.
                if isinstance(ccontent, str):
                    safe_content = ccontent
                else:
                    safe_content = ""

                if ctype == "content":
                    if current_block == "fc":
                        accumulated += "</fc>"
                    elif current_block == "think":
                        accumulated += "</think>"
                    current_block = None
                    assistant_reply += safe_content

                elif ctype == "tool_name" or ctype == "call_arguments":
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
                    reasoning_reply += safe_content

                # Accumulate content (filtered)
                accumulated += safe_content

                yield json.dumps(chunk)
                self._shunt_to_redis_stream(redis, stream_key, chunk)

            # Close dangling tags at end of stream
            if current_block == "fc":
                accumulated += "</fc>"
            elif current_block == "think":
                accumulated += "</think>"

        except Exception as exc:
            LOG.error(f"DEBUG: Stream Exception: {exc}")
            err = {"type": "error", "content": f"GPT-OSS stream error: {exc}"}
            yield json.dumps(err)
            self._shunt_to_redis_stream(redis, stream_key, err)
        finally:
            stop_event.set()

        yield json.dumps({"type": "status", "status": "complete", "run_id": run_id})

        # -----------------------------------------------------------
        # 2. DETECTION & PERSISTENCE
        # -----------------------------------------------------------
        LOG.debug(f"DEBUG: Final Accumulated String for Parsing: {accumulated}")

        # --- FIX: Sanitize tool call format (Name{Args} -> JSON) ---
        if "<fc>" in accumulated:
            try:
                fc_pattern = r"<fc>(.*?)</fc>"
                matches = re.findall(fc_pattern, accumulated, re.DOTALL)
                for original_content in matches:
                    # If it parses as JSON immediately, it's fine.
                    try:
                        json.loads(original_content)
                        continue
                    except json.JSONDecodeError:
                        pass

                    # Pattern: FunctionName {JSON}
                    fix_match = re.match(
                        r"^\s*([a-zA-Z0-9_]+)\s*(\{.*)", original_content, re.DOTALL
                    )
                    if fix_match:
                        func_name = fix_match.group(1)
                        func_args = fix_match.group(2)
                        try:
                            # Use raw_decode to ignore trailing garbage (like repeated structs)
                            parsed_args, _ = json.JSONDecoder().raw_decode(func_args)

                            valid_payload = json.dumps(
                                {"name": func_name, "arguments": parsed_args}
                            )

                            accumulated = accumulated.replace(
                                f"<fc>{original_content}</fc>",
                                f"<fc>{valid_payload}</fc>",
                            )
                            LOG.debug(
                                f"DEBUG: Sanitized tool call structure for: {func_name}"
                            )
                        except Exception as e:
                            LOG.warning(
                                f"DEBUG: Failed to sanitize potential tool call: {e}"
                            )
            except Exception as e:
                LOG.error(f"DEBUG: Error during tool call sanitization: {e}")

        # This triggers the Mixin logic to set internal state
        has_fc = self.parse_and_set_function_calls(accumulated, assistant_reply)

        # Double check state via the Mixin getter
        mixin_state = (
            self.get_function_call_state()
            if hasattr(self, "get_function_call_state")
            else has_fc
        )
        LOG.debug(
            f"DEBUG: Detection Summary -> parse_result: {has_fc}, mixin_state: {mixin_state}"
        )

        message_to_save = assistant_reply

        # Only use 'has_fc' or 'mixin_state' to decide if we structure as a tool call
        if has_fc or mixin_state:
            try:
                # Use regex to pull the content between the injected <fc> tags
                fc_match = re.search(r"<fc>(.*?)</fc>", accumulated, re.DOTALL)
                if fc_match:
                    raw_json = fc_match.group(1).strip()
                    payload_dict = json.loads(raw_json)

                    call_id = f"call_{uuid.uuid4().hex[:8]}"
                    self._current_tool_call_id = call_id

                    # Structure it for the Database/OpenAI compatibility
                    tool_calls_structure = [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": payload_dict.get("name"),
                                "arguments": (
                                    json.dumps(payload_dict.get("arguments", {}))
                                    if isinstance(payload_dict.get("arguments"), dict)
                                    else payload_dict.get("arguments")
                                ),
                            },
                        }
                    ]
                    message_to_save = json.dumps(tool_calls_structure)
                    LOG.info(f"DEBUG: Successfully structured tool call: {call_id}")
            except Exception as e:
                LOG.error(f"DEBUG: Failed to structure tool calls from tags: {e}")
                # Fallback to the accumulated string if formatting fails
                message_to_save = accumulated

        if message_to_save:
            self.finalize_conversation(message_to_save, thread_id, assistant_id, run_id)

        # Update run status based on whether a tool call was detected
        final_status = (
            StatusEnum.pending_action.value
            if (has_fc or mixin_state)
            else StatusEnum.completed.value
        )
        LOG.info(f"DEBUG: Final Run Status determined as: {final_status}")
        self.project_david_client.runs.update_run_status(run_id, final_status)

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
        # Turn 1: Initial Inference
        yield from self.stream(
            thread_id,
            message_id,
            run_id,
            assistant_id,
            model,
            api_key=api_key,
            **kwargs,
        )

        # --- TOOL CHECK ---
        has_tools = False
        if hasattr(self, "get_function_call_state"):
            has_tools = self.get_function_call_state()
            LOG.info(f"DEBUG: process_conversation check -> has_tools: {has_tools}")
        else:
            LOG.error("DEBUG: CRITICAL - self has no get_function_call_state method")

        if has_tools:
            tool_call_id = getattr(self, "_current_tool_call_id", None)
            LOG.info(f"DEBUG: Triggering tool logic for ID: {tool_call_id}")

            yield from self.process_tool_calls(
                thread_id,
                run_id,
                assistant_id,
                tool_call_id=tool_call_id,
                model=model,
                api_key=api_key,
            )

            # Cleanup State
            if hasattr(self, "set_tool_response_state"):
                self.set_tool_response_state(False)
            if hasattr(self, "set_function_call_state"):
                self.set_function_call_state(None)

            self._current_tool_call_id = None
            self._force_refresh = True

            LOG.info(
                "DEBUG: Tool results processed. Starting Turn 2 stream (Final Response)."
            )
            # Turn 2: Final Response after Tool Output
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
        else:
            LOG.info(f"DEBUG: No tools detected. Workflow for run {run_id} finished.")
