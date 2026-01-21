from __future__ import annotations

import json
import os
import uuid
from typing import Any, Generator, Optional

import requests
from dotenv import load_dotenv
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from src.api.entities_api.dependencies import get_redis
from src.api.entities_api.orchestration.engine.orchestrator_core import OrchestratorCore

# --- DIRECT IMPORTS ---
from src.api.entities_api.orchestration.mixins.assistant_cache_mixin import (
    AssistantCacheMixin,
)
from src.api.entities_api.orchestration.mixins.code_execution_mixin import (
    CodeExecutionMixin,
)
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
from src.api.entities_api.orchestration.mixins.shell_execution_mixin import (
    ShellExecutionMixin,
)
from src.api.entities_api.orchestration.mixins.tool_routing_mixin import (
    ToolRoutingMixin,
)
from src.api.entities_api.orchestration.streaming.hyperbolic import (
    HyperbolicDeltaNormalizer,
)
from src.api.entities_api.orchestration.streaming.hyperbolic_async_client import (
    AsyncHyperbolicClient,
)
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
    # 🔒 NORMALIZATION FIX
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

    import json
    import os
    import uuid
    from typing import Any, Dict, Generator, List, Optional

    import requests

    def stream(
        self,
        thread_id: str,
        message_id: Optional[str],
        run_id: str,
        assistant_id: str,
        model: Any,
        *,
        force_refresh: bool = False,
        stream_reasoning: bool = True,
        api_key: Optional[str] = None,
        **kwargs,
    ) -> Generator[str, None, None]:
        redis = get_redis()
        stream_key = f"stream:{run_id}"
        stop_event = self.start_cancellation_monitor(run_id)
        self._current_tool_call_id = None

        try:
            # 1. Setup Context and Model
            if isinstance(model, str) and model.startswith("hyperbolic/"):
                model = model.replace("hyperbolic/", "")
            if mapped := self._get_model_map(model):
                model = mapped

            raw_ctx = self._set_up_context_window(
                assistant_id,
                thread_id,
                trunk=True,
                tools_native=True,
                force_refresh=force_refresh,
            )
            cleaned_ctx, extracted_tools = self.prepare_native_tool_context(raw_ctx)

            # 2. Direct Requests Configuration
            url = (
                os.getenv("HYPERBOLIC_BASE_URL", "https://api.hyperbolic.xyz/v1")
                + "/chat/completions"
            )
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            }
            payload = {
                "messages": cleaned_ctx,
                "tools": extracted_tools,
                "model": model,
                "temperature": kwargs.get("temperature", 0.4),
                "top_p": kwargs.get("top_p", 0.9),
                "max_tokens": kwargs.get("max_tokens", 2048),
                "stream": True,
            }

            # 3. Initiation Signal
            yield json.dumps({"type": "status", "status": "started", "run_id": run_id})

            # State Tracking
            assistant_reply = ""
            reasoning_reply = ""
            current_tool_name: str | None = None
            current_tool_args_buffer: str = ""
            code_mode = False
            self._code_start_index = -1
            self._code_yielded_cursor = 0

            # 4. Execute Streaming Request
            with requests.post(
                url, headers=headers, json=payload, stream=True
            ) as response:
                if response.status_code != 200:
                    raise Exception(
                        f"Hyperbolic API Error ({response.status_code}): {response.text}"
                    )

                for line in response.iter_lines():
                    if stop_event.is_set():
                        break
                    if not line:
                        continue

                    decoded_line = line.decode("utf-8")
                    if not decoded_line.startswith("data: "):
                        continue

                    content_str = decoded_line[6:].strip()
                    if content_str == "[DONE]":
                        break

                    chunk_json = json.loads(content_str)
                    # Normalize the delta using your existing logic or direct access
                    for delta_chunk in HyperbolicDeltaNormalizer.iter_deltas(
                        [chunk_json], run_id
                    ):
                        ctype = delta_chunk["type"]
                        ccontent = delta_chunk["content"]

                        # REASONING CHANNEL
                        if ctype == "reasoning":
                            reasoning_reply += ccontent
                            yield json.dumps(delta_chunk)
                            self._shunt_to_redis_stream(redis, stream_key, delta_chunk)

                        # TOOL CALL CHANNEL
                        elif ctype in ("tool_name", "tool_call"):
                            if ctype == "tool_name":
                                current_tool_name = ccontent
                            else:
                                current_tool_name = ccontent.get("name")
                                args = ccontent.get("arguments", "")
                                current_tool_args_buffer = (
                                    json.dumps(args)
                                    if isinstance(args, dict)
                                    else str(args)
                                )

                        # ARGUMENT STREAMING (HOT CODE)
                        elif ctype == "call_arguments":
                            current_tool_args_buffer += ccontent
                            if current_tool_name in (
                                "code_interpreter",
                                "python",
                                "execute_code",
                            ):
                                if not code_mode:
                                    code_mode = True
                                    start_p = {
                                        "type": "hot_code",
                                        "content": "```python\n",
                                    }
                                    yield json.dumps(start_p)
                                    self._shunt_to_redis_stream(
                                        redis, stream_key, start_p
                                    )

                                (
                                    self._code_start_index,
                                    self._code_yielded_cursor,
                                    hc_payload,
                                ) = self.process_hot_code_buffer(
                                    buffer=current_tool_args_buffer,
                                    start_index=self._code_start_index,
                                    cursor=self._code_yielded_cursor,
                                    redis_client=redis,
                                    stream_key=stream_key,
                                )
                                if hc_payload:
                                    yield hc_payload

                        # CONTENT CHANNEL
                        elif ctype == "content":
                            assistant_reply += ccontent
                            # ... (Keep your existing code_mode detection logic here) ...
                            yield json.dumps(delta_chunk)
                            self._shunt_to_redis_stream(redis, stream_key, delta_chunk)

        except Exception as exc:
            err = {"type": "error", "content": f"Stream error: {str(exc)}"}
            yield json.dumps(err)
            self._shunt_to_redis_stream(redis, stream_key, err)
        finally:
            # 5. Finalize Logic (Persistence)
            accumulated = ""
            if current_tool_name:
                accumulated = json.dumps(
                    {"name": current_tool_name, "arguments": current_tool_args_buffer}
                )

            # ... (Keep your existing normalize/finalize/status update logic here) ...
            stop_event.set()

        yield json.dumps({"type": "status", "status": "complete", "run_id": run_id})

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

            yield from self.process_function_calls(
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
