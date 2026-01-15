from __future__ import annotations
"""
Hyperbolic Ds1 – DeepSeek provider (Refined Stream variant)
───────────────────────────────────────────────────────────
• Intercepts raw stream to suppress <fc> tags server-side.
• Categorizes chunks into 'content' vs 'call_arguments' f or high-fidelity streaming.
• Maintains 'accumulated' buffer for final Regex-based tool orchestration.
"""
import json
import os
from typing import Any, Generator, Optional

from dotenv import load_dotenv
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from src.api.entities_api.dependencies import get_redis
from src.api.entities_api.orchestration.mixins import (
    AssistantCacheMixin,
    CodeExecutionMixin,
    ConsumerToolHandlersMixin,
    ConversationContextMixin,
    FileSearchMixin,
    JsonUtilsMixin,
    PlatformToolHandlersMixin,
    ShellExecutionMixin,
    ToolRoutingMixin,
)
from entities_api.orchestration.engine.orchestrator_core import OrchestratorCore

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
    """Flat bundle → single inheritance in the concrete class."""


class HyperbolicDs1(_ProviderMixins, OrchestratorCore):
    """
    DeepSeek-V3 served by Hyperbolic – streaming & tool orchestration.
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
        self._assistant_cache: dict = assistant_cache or {}
        self.redis = redis or get_redis()
        self.assistant_id = assistant_id
        self.thread_id = thread_id
        self.base_url = base_url or os.getenv("BASE_URL")
        self.api_key = api_key
        self.model_name = extra.get("model_name", "deepseek-ai/DeepSeek-V3")
        self.max_context_window = extra.get("max_context_window", 128000)
        self.threshold_percentage = extra.get("threshold_percentage", 0.8)
        self.setup_services()
        LOG.debug("Hyperbolic-Ds1 provider ready (assistant=%s)", assistant_id)

    @property
    def assistant_cache(self) -> dict:
        return self._assistant_cache

    @assistant_cache.setter
    def assistant_cache(self, value: dict) -> None:
        if hasattr(self, "_assistant_cache"):
            raise AttributeError("assistant_cache already initialised")
        self._assistant_cache = value

    def get_assistant_cache(self) -> dict:
        return self._assistant_cache

    def _get_refined_generator(self, raw_stream: Any, run_id: str) -> Generator[dict, None, None]:
        """
        Internal state machine to filter <fc> tags and categorize content.
        Yields dictionaries ready for JSON serialization.
        """
        tag_start = "<fc>"
        tag_end = "</fc>"
        buffer = ""
        is_in_fc = False

        for token in raw_stream:
            if not token.choices or not token.choices[0].delta:
                continue
            seg = getattr(token.choices[0].delta, "content", "")
            if not seg:
                continue

            for char in seg:
                buffer += char
                if not is_in_fc:
                    # Logic: If buffer could be the start of <fc>, wait.
                    if tag_start.startswith(buffer):
                        if buffer == tag_start:
                            is_in_fc = True
                            buffer = ""
                        continue
                    else:
                        # Flush normal content
                        yield {"type": "content", "content": buffer, "run_id": run_id}
                        buffer = ""
                else:
                    # Logic: Inside <fc>, looking for </fc>
                    if tag_end in buffer:
                        parts = buffer.split(tag_end, 1)
                        if parts[0]:
                            yield {"type": "call_arguments", "content": parts[0], "run_id": run_id}
                        is_in_fc = False
                        buffer = parts[1] if len(parts) > 1 else ""
                    # If buffer is a partial match for </fc>, keep waiting
                    elif any(tag_end.startswith(buffer[i:]) for i in range(len(buffer))):
                        continue
                    else:
                        # Flush tool arguments
                        yield {"type": "call_arguments", "content": buffer, "run_id": run_id}
                        buffer = ""

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
    ) -> Generator[str, None, None]:
        redis = get_redis()
        stream_key = f"stream:{run_id}"
        stop_event = self.start_cancellation_monitor(run_id)

        if mapped := self._get_model_map(model):
            model = mapped

        ctx = self._set_up_context_window(assistant_id, thread_id, trunk=True)
        if model == "deepseek-ai/DeepSeek-R1":
            amended = self._build_amended_system_message(assistant_id=assistant_id)
            ctx = self.replace_system_message(ctx,
                                              json.dumps(amended, ensure_ascii=False, indent=2))

        payload = {
            "model": model,
            "messages": ctx,
            "max_tokens": 10000,
            "temperature": 0.6,
            "stream": True,
        }

        start_chunk = {"type": "status", "status": "started", "run_id": run_id}
        yield json.dumps(start_chunk)
        self._shunt_to_redis_stream(redis, stream_key, start_chunk)

        try:
            client = self._get_openai_client(
                base_url=os.getenv("HYPERBOLIC_BASE_URL"), api_key=api_key
            )
            raw_stream = client.chat.completions.create(**payload)
        except Exception as exc:
            err = {"type": "error", "content": f"client init failed: {exc}"}
            yield json.dumps(err)
            self._shunt_to_redis_stream(redis, stream_key, err)
            return

        assistant_reply = ""  # Final visible text
        accumulated = ""  # Full raw string (including tags) for ToolRoutingMixin
        code_mode = False
        code_buf = ""

        # Using the refined generator for clean streaming
        for chunk in self._get_refined_generator(raw_stream, run_id):
            if stop_event.is_set():
                err = {"type": "error", "content": "Run cancelled"}
                yield json.dumps(err)
                self._shunt_to_redis_stream(redis, stream_key, err)
                break

            ctype = chunk["type"]
            ccontent = chunk["content"]

            # Maintain the background buffers
            if ctype == "content":
                assistant_reply += ccontent
                accumulated += ccontent
            else:
                # Reconstruct tags in 'accumulated' so Regex still finds them later
                # We only do this once per switch if we wanted to be efficient,
                # but adding the raw content here is enough as long as the
                # finalize_conversation / parse logic handles the result.
                accumulated += ccontent

            # Handle Code Interpreter logic
            if ctype == "content":
                parse_ci = getattr(self, "parse_code_interpreter_partial", None)
                ci_match = parse_ci(accumulated) if parse_ci and (not code_mode) else None

                if ci_match:
                    code_mode = True
                    code_buf = ci_match.get("code", "")
                    start = {"type": "hot_code", "content": "```python\n"}
                    yield json.dumps(start)
                    self._shunt_to_redis_stream(redis, stream_key, start)
                    if code_buf and hasattr(self, "_process_code_interpreter_chunks"):
                        res, code_buf = self._process_code_interpreter_chunks("", code_buf)
                        for r in res:
                            yield r
                            self._shunt_to_redis_stream(redis, stream_key, json.loads(r))
                    continue

                if code_mode:
                    if hasattr(self, "_process_code_interpreter_chunks"):
                        res, code_buf = self._process_code_interpreter_chunks(ccontent, code_buf)
                        for r in res:
                            yield r
                            self._shunt_to_redis_stream(redis, stream_key, json.loads(r))
                    else:
                        hot = {"type": "hot_code", "content": ccontent}
                        yield json.dumps(hot)
                        self._shunt_to_redis_stream(redis, stream_key, hot)
                    continue

            # Yield refined chunk to client
            yield json.dumps(chunk)
            self._shunt_to_redis_stream(redis, stream_key, chunk)

        # Finalize
        end_chunk = {"type": "status", "status": "complete", "run_id": run_id}
        yield json.dumps(end_chunk)
        self._shunt_to_redis_stream(redis, stream_key, end_chunk)

        if assistant_reply:
            self.finalize_conversation(assistant_reply, thread_id, assistant_id, run_id)

        # Note: We use accumulated here. For this to work perfectly,
        # ensure parse_and_set_function_calls handles the content provided.
        if accumulated and self.parse_and_set_function_calls(accumulated, assistant_reply):
            self.project_david_client.runs.update_run_status(run_id,
                                                             StatusEnum.pending_action.value)
        else:
            self.project_david_client.runs.update_run_status(run_id, StatusEnum.completed.value)

    def process_conversation(
        self,
        thread_id: str,
        message_id: str,
        run_id: str,
        assistant_id: str,
        model: Any,
        *,
        stream_reasoning: bool = False,
        api_key: Optional[str] = None,
    ) -> Generator[str, None, None]:
        yield from self.stream(thread_id, message_id, run_id, assistant_id, model,
                               stream_reasoning=stream_reasoning, api_key=api_key)

        if self.get_function_call_state():
            yield from self.process_function_calls(thread_id, run_id, assistant_id, model=model,
                                                   api_key=api_key)
            self.set_tool_response_state(False)
            self.set_function_call_state(None)
            yield from self.stream(thread_id, None, run_id, assistant_id, model,
                                   stream_reasoning=stream_reasoning, api_key=api_key)
