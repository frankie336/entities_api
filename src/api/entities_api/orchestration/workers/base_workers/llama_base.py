from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Generator, Optional

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


class LlamaBaseWorker(_ProviderMixins, OrchestratorCore, ABC):
    """
    Abstract Base for Llama-3.3 Providers (Hyperbolic, Together, etc.).
    """

    def __init__(
        self, *, assistant_id=None, thread_id=None, redis=None, **extra
    ) -> None:
        self._assistant_cache = extra.get("assistant_cache") or {}
        self.redis = redis or get_redis()
        self.assistant_id = assistant_id
        self.thread_id = thread_id
        self.api_key = extra.get("api_key")

        self.model_name = extra.get("model_name", "meta-llama/Llama-3.3-70B-Instruct")
        self.max_context_window = extra.get("max_context_window", 128000)
        self.threshold_percentage = extra.get("threshold_percentage", 0.8)

        self.setup_services()
        LOG.debug(f"{self.__class__.__name__} ready (assistant={assistant_id})")

    @abstractmethod
    def _get_client_instance(self, api_key: str):
        """Return the specific provider client."""
        pass

    @abstractmethod
    def _execute_stream_request(self, client, payload: dict) -> Any:
        """
        Execute the stream request.
        Hyperbolic uses async_to_sync wrapper, Together uses standard sync.
        """
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

        # Use instance key if not provided
        api_key = api_key or self.api_key

        # --- FIX 1: Early Variable Initialization (Safety) ---
        self._current_tool_call_id = None
        assistant_reply = ""
        reasoning_reply = ""
        accumulated = ""
        current_block = None
        # -----------------------------------------------------

        try:
            # 1. Clean Model ID
            if isinstance(model, str) and model.startswith("hyperbolic/"):
                model = model.replace("hyperbolic/", "")
            if mapped := self._get_model_map(model):
                model = mapped

            # 2. Context & Tool Extraction
            raw_ctx = self._set_up_context_window(
                assistant_id,
                thread_id,
                trunk=True,
                structured_tool_call=False,
                force_refresh=force_refresh,
            )

            # Llama 3.3 typically handles tools via native context preparation
            # This Mixin method ensures the prompt format is correct
            cleaned_ctx, extracted_tools = self.prepare_native_tool_context(raw_ctx)

            if not api_key:
                yield json.dumps({"type": "error", "content": "Missing API key."})
                return

            client = self._get_client_instance(api_key=api_key)

            payload = {
                "messages": raw_ctx,
                "model": model,
                "temperature": kwargs.get("temperature", 0.6),
                "top_p": 0.9,
                "stream": True,
                # Explicit stop token for Llama tool use
                "stop": ["</fc>"],
            }

            # 3. Get the iterator (Abstracted)
            raw_stream = self._execute_stream_request(client, payload)

            yield json.dumps({"type": "status", "status": "started", "run_id": run_id})

            # 4. Standardized Chunk Processing (With Tag Injection)
            for chunk in HyperbolicDeltaNormalizer.iter_deltas(raw_stream, run_id):
                if stop_event.is_set():
                    break

                ctype, ccontent = chunk["type"], chunk["content"]

                # Ensure content is string for accumulation
                safe_content = ccontent if isinstance(ccontent, str) else ""

                if ctype == "content":
                    if current_block == "fc":
                        accumulated += "</fc>"
                    elif current_block == "think":
                        accumulated += "</think>"
                    current_block = None
                    assistant_reply += safe_content

                elif ctype == "tool_name" or ctype == "call_arguments":
                    # Determine if we need to open an <fc> block
                    if current_block != "fc":
                        if current_block == "think":
                            accumulated += "</think>"
                        accumulated += "<fc>"
                        current_block = "fc"

                    # If it's a native tool call dict (legacy path), stringify it
                    if isinstance(ccontent, dict):
                        safe_content = json.dumps(ccontent)

                elif ctype == "tool_call":
                    # Full tool call object fallback
                    if current_block != "fc":
                        accumulated += "<fc>"
                        current_block = "fc"
                    if isinstance(ccontent, dict):
                        safe_content = json.dumps(ccontent)

                elif ctype == "reasoning":
                    if current_block != "think":
                        if current_block == "fc":
                            accumulated += "</fc>"
                        accumulated += "<think>"
                        current_block = "think"
                    reasoning_reply += safe_content

                # Accumulate content (with correct flow)
                accumulated += safe_content

                # --- REFACTOR: Prevent yielding call_arguments ---
                if ctype != "call_arguments":
                    yield json.dumps(chunk)
                # -------------------------------------------------

                self._shunt_to_redis_stream(redis, stream_key, chunk)

            # Close dangling tags at end of stream
            if current_block == "fc":
                accumulated += "</fc>"
            elif current_block == "think":
                accumulated += "</think>"

        except Exception as exc:
            err = {"type": "error", "content": f"Stream error: {exc}"}
            yield json.dumps(err)
            self._shunt_to_redis_stream(redis, stream_key, err)
        finally:
            stop_event.set()

        yield json.dumps({"type": "status", "status": "complete", "run_id": run_id})

        # ------------------------------------------------------------------
        # 💉 FIX 2: TIMEOUT PREVENTION (Keep-Alive Heartbeat)
        # ------------------------------------------------------------------
        yield json.dumps({"type": "status", "status": "processing", "run_id": run_id})

        # ------------------------------------------------------------------
        # 🔒 FIX 3: DETECTION & PERSISTENCE (The "Special Method")
        # ------------------------------------------------------------------
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

                    # Pattern: FunctionName {JSON} (Handles native Llama stream format)
                    fix_match = re.match(
                        r"^\s*([a-zA-Z0-9_]+)\s*(\{.*)", original_content, re.DOTALL
                    )
                    if fix_match:
                        func_name = fix_match.group(1)
                        func_args = fix_match.group(2)
                        try:
                            # Use raw_decode to ignore trailing garbage
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

        # Trigger Mixin logic
        has_fc = self.parse_and_set_function_calls(accumulated, assistant_reply)

        # Double check state via the Mixin getter
        mixin_state = (
            self.get_function_call_state()
            if hasattr(self, "get_function_call_state")
            else has_fc
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
        self.project_david_client.runs.update_run_status(run_id, final_status)

    def process_conversation(
        self, thread_id, message_id, run_id, assistant_id, model, api_key=None, **kwargs
    ):
        """Standard Llama process loop."""
        yield from self.stream(
            thread_id,
            message_id,
            run_id,
            assistant_id,
            model,
            api_key=api_key,
            **kwargs,
        )

        if self.get_function_call_state():
            yield from self.process_tool_calls(
                thread_id, run_id, assistant_id, model=model, api_key=api_key
            )
            self.set_tool_response_state(False)
            self.set_function_call_state(None)

            yield from self.stream(
                thread_id, None, run_id, assistant_id, model, api_key=api_key, **kwargs
            )
