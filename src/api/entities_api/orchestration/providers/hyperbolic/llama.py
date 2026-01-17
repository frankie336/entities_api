# src/api/entities_api/orchestration/providers/hyperbolic/llama.py
from __future__ import annotations

import json
import os
from typing import Any, Generator, Optional

import requests
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


class HyperbolicLlama33(_ProviderMixins, OrchestratorCore):
    """
    Modular Meta-Llama-3-33B Provider.
    Refactored to use inline requests streaming to guarantee compatibility.
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

        # Attributes required by Truncator logic
        self.model_name = extra.get("model_name", "meta-llama/Llama-3.3-70B-Instruct")
        self.max_context_window = extra.get("max_context_window", 128000)
        self.threshold_percentage = extra.get("threshold_percentage", 0.8)

        self.setup_services()
        LOG.debug("Hyperbolic-Llama provider ready (assistant=%s)", assistant_id)

    @property
    def assistant_cache(self) -> dict:
        return self._assistant_cache

    @assistant_cache.setter
    def assistant_cache(self, value: dict) -> None:
        if hasattr(self, "_assistant_cache") and self._assistant_cache:
            raise AttributeError("assistant_cache already initialised")
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
        api_key: Optional[str] = None,
        **kwargs,
    ) -> Generator[str, None, None]:
        redis = get_redis()
        stream_key = f"stream:{run_id}"
        stop_event = self.start_cancellation_monitor(run_id)

        try:
            # 1. Standard model cleanup
            if isinstance(model, str) and model.startswith("hyperbolic/"):
                model = model.replace("hyperbolic/", "")
            if mapped := self._get_model_map(model):
                model = mapped

            # 2. Get the context (contains the 'tools:\n[' string in system message)
            raw_ctx = self._set_up_context_window(assistant_id, thread_id, trunk=True)

            # --- TOOL EXTRACTION LOGIC ---
            cleaned_ctx = []
            extracted_tools = None

            for msg in raw_ctx:
                content = msg.get("content") or ""
                # Detect the tools block injected by the Mixin
                if msg.get("role") == "system" and "tools:\n[" in content:
                    try:
                        parts = content.split("tools:\n", 1)
                        system_text = parts[0].strip()
                        tools_json_str = parts[1].strip()

                        # Parse the tools back into a list
                        extracted_tools = json.loads(tools_json_str)

                        # Replace the message with one that doesn't have the tools block
                        cleaned_ctx.append(
                            {
                                "role": "system",
                                "content": (
                                    system_text
                                    if system_text
                                    else "You are a helpful assistant."
                                ),
                            }
                        )
                        continue
                    except Exception as e:
                        LOG.error(
                            "Failed to extract/parse tools from system message: %s", e
                        )

                # Clean up any other fields (id, created_at) that might break raw requests
                cleaned_ctx.append(
                    {"role": msg["role"], "content": msg.get("content") or ""}
                )

            if not api_key:
                yield json.dumps({"type": "error", "content": "Missing API key."})
                return

            # --- PAYLOAD CONSTRUCTION ---
            url = "https://api.hyperbolic.xyz/v1/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            }

            payload = {
                "messages": cleaned_ctx,
                "model": model,
                "temperature": kwargs.get("temperature", 0.6),
                "top_p": 0.9,
                "stream": True,
            }

            # Inject tools into the native API parameter if we found them
            if extracted_tools:
                payload["tools"] = extracted_tools
                # If tools are present, Llama handles 'role: tool' in the history correctly.

            # --- INLINE REQUESTS STREAMING ---
            def raw_json_generator():
                # Use a timeout for the initial connection
                with requests.post(
                    url, headers=headers, json=payload, stream=True, timeout=30
                ) as resp:
                    if resp.status_code != 200:
                        error_text = resp.text
                        LOG.error(f"Hyperbolic API Error: {error_text}")
                        yield {
                            "type": "error",
                            "content": f"API Error {resp.status_code}: {error_text}",
                        }
                        return

                    for line in resp.iter_lines():
                        if stop_event.is_set():
                            break
                        if not line:
                            continue
                        decoded = line.decode("utf-8")
                        if decoded.startswith("data: "):
                            content = decoded[6:]
                            if content == "[DONE]":
                                break
                            try:
                                yield json.loads(content)
                            except json.JSONDecodeError:
                                continue

            yield json.dumps({"type": "status", "status": "started", "run_id": run_id})

            assistant_reply, accumulated, current_block = "", "", None
            code_mode = False

            # Feed the generator into the Universal Normalizer
            for chunk in HyperbolicDeltaNormalizer.iter_deltas(
                raw_json_generator(), run_id
            ):
                # Handle error dicts yielded by the generator
                if isinstance(chunk, dict) and chunk.get("type") == "error":
                    yield json.dumps(chunk)
                    break

                if stop_event.is_set():
                    err = {"type": "error", "content": "Run cancelled"}
                    yield json.dumps(err)
                    self._shunt_to_redis_stream(redis, stream_key, err)
                    break

                ctype, ccontent = chunk["type"], chunk["content"]

                # --- METHODOLOGY: TAG INJECTION ---
                if ctype == "content":
                    if current_block == "fc":
                        accumulated += "</fc>"
                    elif current_block == "think":
                        accumulated += "</think>"
                    current_block = None
                    assistant_reply += ccontent
                elif ctype == "call_arguments":
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

                accumulated += ccontent

                # --- CODE INTERPRETER INTERLEAVING ---
                if ctype == "content":
                    parse_ci = getattr(self, "parse_code_interpreter_partial", None)
                    ci_match = (
                        parse_ci(accumulated) if parse_ci and not code_mode else None
                    )
                    if ci_match:
                        code_mode = True
                        code_buf = ci_match.get("code", "")
                        start = {"type": "hot_code", "content": "```python\n"}
                        yield json.dumps(start)
                        self._shunt_to_redis_stream(redis, stream_key, start)
                        if hasattr(self, "_process_code_interpreter_chunks"):
                            res, code_buf = self._process_code_interpreter_chunks(
                                "", code_buf
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
                                ccontent, code_buf
                            )
                            for r in res:
                                yield r
                                self._shunt_to_redis_stream(
                                    redis, stream_key, json.loads(r)
                                )
                        else:
                            hot = {"type": "hot_code", "content": ccontent}
                            yield json.dumps(hot)
                            self._shunt_to_redis_stream(redis, stream_key, hot)
                        continue

                yield json.dumps(chunk)
                self._shunt_to_redis_stream(redis, stream_key, chunk)

        except Exception as exc:
            err = {"type": "error", "content": f"Llama stream error: {exc}"}
            yield json.dumps(err)
            self._shunt_to_redis_stream(redis, stream_key, err)
        finally:
            # Ensure tags are closed if stream ends abruptly
            if current_block == "fc":
                accumulated += "</fc>"
            elif current_block == "think":
                accumulated += "</think>"
            stop_event.set()

        # FINAL CLOSE-OUT
        end_chunk = {"type": "status", "status": "complete", "run_id": run_id}
        yield json.dumps(end_chunk)
        self._shunt_to_redis_stream(redis, stream_key, end_chunk)

        if assistant_reply:
            self.finalize_conversation(assistant_reply, thread_id, assistant_id, run_id)

        if accumulated and self.parse_and_set_function_calls(
            accumulated, assistant_reply
        ):
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
        stream_reasoning: bool = True,
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

        if self.get_function_call_state():
            yield from self.process_function_calls(
                thread_id, run_id, assistant_id, model=model, api_key=api_key
            )
            self.set_tool_response_state(False)
            self.set_function_call_state(None)
            yield from self.stream(
                thread_id, None, run_id, assistant_id, model, api_key=api_key, **kwargs
            )
