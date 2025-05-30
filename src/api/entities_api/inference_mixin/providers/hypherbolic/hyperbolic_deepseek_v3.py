from __future__ import annotations

import json
import os
import re
from typing import Any, Generator, Optional

from dotenv import load_dotenv
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from entities_api.dependencies import get_redis
from entities_api.inference_mixin.mixins import (AssistantCacheMixin,
                                                 CodeExecutionMixin,
                                                 ConsumerToolHandlersMixin,
                                                 ConversationContextMixin,
                                                 FileSearchMixin,
                                                 JsonUtilsMixin,
                                                 PlatformToolHandlersMixin,
                                                 ShellExecutionMixin,
                                                 ToolRoutingMixin)
from entities_api.inference_mixin.orchestrator_core import OrchestratorCore

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
    """Flat mix-in bundle so the concrete provider only inherits once."""


class HyperbolicDeepSeekV3Inference(_ProviderMixins, OrchestratorCore):
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
    ):
        self._assistant_cache = assistant_cache or {}
        self.redis = redis or get_redis()
        self.assistant_id = assistant_id
        self.thread_id = thread_id
        self.base_url = base_url or os.getenv("HYPERBOLIC_BASE_URL")
        self.api_key = api_key

        self.model_name = extra.get("model_name", "deepseek-ai/DeepSeek-V3")
        self.max_context_window = extra.get("max_context_window", 128_000)
        self.threshold_percentage = extra.get("threshold_percentage", 0.8)

        self.setup_services()
        LOG.debug(
            "HyperbolicDeepSeekV3Inference ready (assistant=%s)",
            assistant_id or "<lazy>",
        )

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

    def _filter_fc(self, chunk_json: str) -> Optional[str]:
        try:
            if json.loads(chunk_json).get("type") == "function_call":
                return None
        except Exception:
            pass
        return chunk_json

    def setup_services(self):
        LOG.debug("HyperbolicDeepSeekV3Inference specific setup completed.")

    def stream(
        self,
        thread_id: str,
        message_id: str,
        run_id: str,
        assistant_id: str,
        model: Any,
        *,
        stream_reasoning: bool = True,
        api_key: Optional[str] = None,
    ) -> Generator[str, None, None]:
        redis = self.redis
        stream_key = f"stream:{run_id}"
        self.start_cancellation_listener(run_id)

        if mapped := self._get_model_map(model):
            model = mapped

        payload = {
            "model": model,
            "messages": self._set_up_context_window(
                assistant_id, thread_id, trunk=True
            ),
            "max_tokens": None,
            "temperature": 0.6,
            "stream": True,
        }

        try:
            client = self._get_openai_client(
                base_url=self.base_url,
                api_key=api_key or self.api_key,
            )
        except Exception as exc:
            err = {"type": "error", "content": f"Hyperbolic client init failed: {exc}"}
            raw = json.dumps(err)
            if p := self._filter_fc(raw):
                yield p
            self._shunt_to_redis_stream(redis, stream_key, err)
            return

        assistant_reply = ""
        accumulated = ""
        reasoning_buf = ""
        in_reasoning = False
        code_mode = False
        code_buf = ""

        try:
            response = client.chat.completions.create(**payload)
            sse_iter = getattr(response, "_iterator", response)

            for sse in sse_iter:
                if self.check_cancellation_flag():
                    cancel = {"type": "error", "content": "Run cancelled"}
                    raw = json.dumps(cancel)
                    if p := self._filter_fc(raw):
                        yield p
                    self._shunt_to_redis_stream(redis, stream_key, cancel)
                    break

                raw_data = (
                    (getattr(sse, "data", "") or "").removeprefix("data:").strip()
                )
                parts = raw_data.replace("}{", "}§{").split("§")

                for part in parts:
                    try:
                        data = json.loads(part)
                    except json.JSONDecodeError:
                        LOG.error("Malformed JSON fragment: %r", part)
                        continue

                    choices = data.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})

                    dr = delta.get("reasoning_content", "")
                    if dr and stream_reasoning:
                        chunk = {"type": "reasoning", "content": dr}
                        raw = json.dumps(chunk)
                        if p := self._filter_fc(raw):
                            yield p
                        self._shunt_to_redis_stream(redis, stream_key, chunk)

                    dc = delta.get("content", "")
                    if not dc:
                        continue

                    for seg in filter(None, re.split(r"(<think>|</think>)", dc)):
                        if seg in ("<think>", "</think>"):
                            in_reasoning = seg == "<think>"
                            if stream_reasoning:
                                chunk = {"type": "reasoning", "content": seg}
                                raw = json.dumps(chunk)
                                if p := self._filter_fc(raw):
                                    yield p
                                self._shunt_to_redis_stream(redis, stream_key, chunk)
                            continue

                        if in_reasoning:
                            reasoning_buf += seg
                            if stream_reasoning:
                                chunk = {"type": "reasoning", "content": seg}
                                raw = json.dumps(chunk)
                                if p := self._filter_fc(raw):
                                    yield p
                                self._shunt_to_redis_stream(redis, stream_key, chunk)
                            continue

                        assistant_reply += seg
                        accumulated += seg

                        parse_ci = getattr(self, "parse_code_interpreter_partial", None)
                        partial = parse_ci(accumulated) if parse_ci else None

                        if not code_mode and partial:
                            code_mode = True
                            code_buf = partial["code"]
                            start = {"type": "hot_code", "content": "```python\n"}
                            raw = json.dumps(start)
                            if p := self._filter_fc(raw):
                                yield p
                            self._shunt_to_redis_stream(redis, stream_key, start)
                            if code_buf and hasattr(
                                self, "_process_code_interpreter_chunks"
                            ):
                                res, code_buf = self._process_code_interpreter_chunks(
                                    "", code_buf
                                )
                                for r in res:
                                    if p := self._filter_fc(r):
                                        yield p
                                    self._shunt_to_redis_stream(
                                        redis, stream_key, json.loads(r)
                                    )
                            continue

                        if code_mode:
                            if hasattr(self, "_process_code_interpreter_chunks"):
                                res, code_buf = self._process_code_interpreter_chunks(
                                    seg, code_buf
                                )
                                for r in res:
                                    if p := self._filter_fc(r):
                                        yield p
                                    self._shunt_to_redis_stream(
                                        redis, stream_key, json.loads(r)
                                    )
                            else:
                                chunk = {"type": "hot_code", "content": seg}
                                raw = json.dumps(chunk)
                                if p := self._filter_fc(raw):
                                    yield p
                                self._shunt_to_redis_stream(redis, stream_key, chunk)
                            continue

                        chunk = {"type": "content", "content": seg}
                        raw = json.dumps(chunk)
                        if p := self._filter_fc(raw):
                            yield p
                        self._shunt_to_redis_stream(redis, stream_key, chunk)

        except Exception as exc:
            err = {"type": "error", "content": f"Hyperbolic SDK error: {exc}"}
            raw = json.dumps(err)
            if p := self._filter_fc(raw):
                yield p
            self._shunt_to_redis_stream(redis, stream_key, err)
            return

        if assistant_reply:
            self.finalize_conversation(
                reasoning_buf + assistant_reply, thread_id, assistant_id, run_id
            )

        if accumulated and self.parse_and_set_function_calls(
            accumulated, assistant_reply
        ):
            self.projectdavid_common_client.runs.update_run_status(
                run_id, StatusEnum.pending_action.value
            )
        elif not self.get_function_call_state():
            self.projectdavid_common_client.runs.update_run_status(
                run_id, StatusEnum.completed.value
            )

        if reasoning_buf:
            LOG.info("Run %s: final reasoning length %d", run_id, len(reasoning_buf))

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
        yield from self.stream(
            thread_id,
            message_id,
            run_id,
            assistant_id,
            model,
            stream_reasoning=stream_reasoning,
            api_key=api_key,
        )

        if self.get_function_call_state():
            yield from self.process_function_calls(
                thread_id, run_id, assistant_id, model=model, api_key=api_key
            )
            yield from self.stream(
                thread_id,
                message_id,
                run_id,
                assistant_id,
                model,
                stream_reasoning=stream_reasoning,
                api_key=api_key,
            )
