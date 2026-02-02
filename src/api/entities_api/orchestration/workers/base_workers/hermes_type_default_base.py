from __future__ import annotations

import json
import os
import re
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, Generator, Optional

from dotenv import load_dotenv
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from entities_api.clients.async_to_sync import async_to_sync_stream
# --- STREAMING & NORMALIZATION ---
from entities_api.clients.delta_normalizer import DeltaNormalizer
from src.api.entities_api.dependencies import get_redis
from src.api.entities_api.orchestration.engine.orchestrator_core import \
    OrchestratorCore
# --- MIXINS ---
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
    """Mixins bundle for DeepCogito Worker."""


class HermesDefaultBaseWorker(_ProviderMixins, OrchestratorCore, ABC):
    """
    Dedicated worker for 'deepcogito/cogito-v2-preview-llama-405B'.
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

        # Model Defaults
        self.model_name = extra.get(
            "model_name", "deepcogito/cogito-v2-preview-llama-405B"
        )

        # Define Max Context Window (Required by ConversationTruncator)
        self.max_context_window = extra.get("max_context_window", 128000)
        self.threshold_percentage = extra.get("threshold_percentage", 0.8)

        self._current_tool_call_id: str | None = None
        # [NEW] Holding variable for the parsed tool payload to pass between methods
        self._pending_tool_payload: Optional[Dict[str, Any]] = None
        # [NEW] Holding variable for the parsed decision payload
        self._decision_payload: Optional[Dict[str, Any]] = None

        self.setup_services()
        LOG.debug("DeepCogito worker initialized (assistant=%s)", assistant_id)

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
        import re
        import uuid

        redis = get_redis()
        stream_key = f"stream:{run_id}"
        stop_event = self.start_cancellation_monitor(run_id)

        # --- FIX 1: Early Variable Initialization (Safety) ---
        self._current_tool_call_id = None
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
                if "tools" in payload:
                    del payload["tools"]

            raw_stream = client.stream_chat_completion(**payload)
            yield json.dumps({"type": "status", "status": "started", "run_id": run_id})

            token_iterator = async_to_sync_stream(raw_stream)

            # -----------------------------------------------------------
            # 1. PROCESS DELTAS & INJECT TAGS
            # -----------------------------------------------------------
            for chunk in DeltaNormalizer.iter_deltas(token_iterator, run_id):
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

                # [NEW] Decision Handling
                elif ctype == "decision":
                    decision_buffer += safe_content
                    if current_block == "fc":
                        accumulated += "</fc>"
                    elif current_block == "think":
                        accumulated += "</think>"
                    current_block = "decision"

                # Accumulate content (filtered)
                accumulated += safe_content

                # --- REFACTOR: Prevent yielding call_arguments ---
                # This prevents the "KeyError: name" in the consumer by holding back
                # partial tool chunks while still accumulating them in 'accumulated'
                # Note: We allow 'decision' to pass through.
                if ctype not in ("tool_name", "call_arguments"):
                    yield json.dumps(chunk)
                # -------------------------------------------------

                self._shunt_to_redis_stream(redis, stream_key, chunk)

            # Close dangling tags at end of stream
            if current_block == "fc":
                accumulated += "</fc>"
            elif current_block == "think":
                accumulated += "</think>"

        except Exception as exc:
            LOG.error(f"DEBUG: Stream Exception: {exc}")
            err = {"type": "error", "content": f"Stream error: {exc}"}
            yield json.dumps(err)
            self._shunt_to_redis_stream(redis, stream_key, err)
        finally:
            stop_event.set()

        yield json.dumps({"type": "status", "status": "complete", "run_id": run_id})

        # --- [NEW] Validate and Save Decision Payload ---
        if decision_buffer:
            try:
                self._decision_payload = json.loads(decision_buffer.strip())
                LOG.info(f"Decision payload validated: {self._decision_payload}")
            except json.JSONDecodeError as e:
                LOG.error(f"Failed to parse decision payload: {e}")

        # ------------------------------------------------------------------
        # 💉 FIX 2: TIMEOUT PREVENTION (Keep-Alive Heartbeat)
        # ------------------------------------------------------------------
        # This prevents the client from timing out while we do the heavy parsing below
        yield json.dumps({"type": "status", "status": "processing", "run_id": run_id})

        # -----------------------------------------------------------
        # 2. DETECTION & PERSISTENCE
        # -----------------------------------------------------------
        LOG.debug(f"DEBUG: Final Accumulated String for Parsing: {accumulated}")

        # --- Sanitize tool call format (Name{Args} -> JSON) ---
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

                    # [NEW] Ensure this is set for process_conversation to pick up
                    self._pending_tool_payload = payload_dict

                    LOG.info(f"DEBUG: Successfully structured tool call: {call_id}")
            except Exception as e:
                LOG.error(f"DEBUG: Failed to structure tool calls from tags: {e}")
                # FIX 3: Fallback to the accumulated string if formatting fails
                # This prevents data loss if the regex or JSON parse fails
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

    def _persist_conversation(
        self, accumulated, assistant_reply, thread_id, assistant_id, run_id
    ):
        """Handles parsing of the accumulated string and saving to DB."""
        has_fc = self.parse_and_set_function_calls(accumulated, assistant_reply)
        message_to_save = assistant_reply

        if has_fc:
            try:
                # Extract content between <fc> tags
                fc_match = re.search(r"<fc>(.*?)</fc>", accumulated, re.DOTALL)
                if fc_match:
                    raw_json = fc_match.group(1).strip()
                    payload_dict = json.loads(raw_json)

                    # Generate a new ID if one wasn't captured
                    call_id = f"call_{uuid.uuid4().hex[:8]}"
                    self._current_tool_call_id = call_id

                    # Format for DB (OpenAI Standard)
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
            except Exception as e:
                LOG.error(f"Failed to structure tool calls: {e}")
                message_to_save = accumulated

        if message_to_save:
            self.finalize_conversation(message_to_save, thread_id, assistant_id, run_id)

        # Update Run Status
        final_status = (
            StatusEnum.pending_action.value if has_fc else StatusEnum.completed.value
        )
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
        # 1. Initial Turn
        yield from self.stream(
            thread_id,
            message_id,
            run_id,
            assistant_id,
            model,
            api_key=api_key,
            **kwargs,
        )

        # 2. Check for Tool Execution
        has_tools = False
        if hasattr(self, "get_function_call_state"):
            has_tools = self.get_function_call_state()

        if has_tools:
            tool_call_id = getattr(self, "_current_tool_call_id", None)
            LOG.info(f"Executing tool logic for ID: {tool_call_id}")

            # [NEW] Retrieve decision payload
            current_decision = getattr(self, "_decision_payload", None)

            # Execute Tools
            yield from self.process_tool_calls(
                thread_id,
                run_id,
                assistant_id,
                tool_call_id=tool_call_id,
                model=model,
                api_key=api_key,
                decision=current_decision,  # [NEW] Pass telemetry
            )

            # Cleanup
            if hasattr(self, "set_tool_response_state"):
                self.set_tool_response_state(False)
            if hasattr(self, "set_function_call_state"):
                self.set_function_call_state(None)

            self._current_tool_call_id = None
            self._decision_payload = None  # [NEW] Cleanup

            # 3. Final Response Turn
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
