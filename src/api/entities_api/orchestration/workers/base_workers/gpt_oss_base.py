from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, AsyncGenerator, Optional

from dotenv import load_dotenv
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

# --- DEPENDENCIES ---
from src.api.entities_api.dependencies import get_redis
from src.api.entities_api.orchestration.engine.orchestrator_core import OrchestratorCore

# --- MIXINS ---
from src.api.entities_api.orchestration.mixins.providers import _ProviderMixins
from src.api.entities_api.orchestration.streaming.hyperbolic import HyperbolicDeltaNormalizer

load_dotenv()
LOG = LoggingUtility()


class GptOssBaseWorker(
    _ProviderMixins,
    OrchestratorCore,  # Base logic comes last
    ABC,  # ABC can remain if needed, usually redundant if Core has it
):
    """
    Async Base for openai/gpt-oss-120b Providers.
    Encapsulates logic for decision buffering, tool normalization, and streaming.
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
        self._assistant_cache: dict = assistant_cache or extra.get("assistant_cache") or {}
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
        self._pending_tool_payload: Optional[Dict[str, Any]] = None
        self._decision_payload: Optional[Dict[str, Any]] = None

        self.setup_services()

        # Ensure Runtime Safety for Mixins
        if not hasattr(self, "get_function_call_state"):
            LOG.error("CRITICAL: ToolRoutingMixin failed to load. Monkey-patching.")
            self.get_function_call_state = lambda: False
            self.set_function_call_state = lambda x: None
            self.set_tool_response_state = lambda x: None

        LOG.debug("Hyperbolic-GptOss provider ready (assistant=%s)", assistant_id)

    @abstractmethod
    def _get_client_instance(self, api_key: str):
        pass

    @property
    def assistant_cache(self) -> dict:
        return self._assistant_cache

    @assistant_cache.setter
    def assistant_cache(self, value: dict) -> None:
        self._assistant_cache = value

    async def stream(
        self,
        thread_id: str,
        message_id: str | None,
        run_id: str,
        assistant_id: str,
        model: Any,
        *,
        force_refresh: bool = False,
        stream_reasoning: bool = False,
        api_key: str | None = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        redis = self.redis
        stream_key = f"stream:{run_id}"
        stop_event = self.start_cancellation_monitor(run_id)

        # Reset internal state
        self._current_tool_call_id = None
        self._pending_tool_payload = None
        self._decision_payload = None

        assistant_reply = ""
        accumulated = ""
        reasoning_reply = ""
        decision_buffer = ""
        current_block = None

        try:
            # Map model if necessary
            if hasattr(self, "_get_model_map") and (mapped := self._get_model_map(model)):
                model = mapped

            # Prepare context
            raw_ctx = await self._set_up_context_window(
                assistant_id,
                thread_id,
                trunk=True,
                structured_tool_call=True,
                force_refresh=force_refresh,
                decision_telemetry=False,
            )
            cleaned_ctx, extracted_tools = self.prepare_native_tool_context(raw_ctx)

            if not api_key:
                err_msg = json.dumps({"type": "error", "content": "Missing Hyperbolic API key."})
                yield err_msg
                return

            client = self._get_client_instance(api_key=api_key)

            raw_stream = client.stream_chat_completion(
                messages=cleaned_ctx,
                model=model,
                tools=None if stream_reasoning else extracted_tools,
                temperature=kwargs.get("temperature", 0.4),
                **kwargs,
            )

            yield json.dumps({"type": "status", "status": "started", "run_id": run_id})

            # -------------------------------
            # 1. Process deltas asynchronously
            # -------------------------------
            async for chunk in HyperbolicDeltaNormalizer.async_iter_deltas(raw_stream, run_id):
                if stop_event.is_set():
                    break

                ctype = chunk.get("type")
                ccontent = chunk.get("content") or ""
                safe_content = ccontent if isinstance(ccontent, str) else ""

                # Manage internal accumulation blocks
                if ctype == "content":
                    if current_block == "fc":
                        accumulated += "</fc>"
                    elif current_block == "think":
                        accumulated += "</think>"
                    current_block = None
                    assistant_reply += safe_content

                elif ctype in ("tool_name", "call_arguments"):
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

                elif ctype == "decision":
                    decision_buffer += safe_content
                    if current_block == "fc":
                        accumulated += "</fc>"
                    elif current_block == "think":
                        accumulated += "</think>"
                    current_block = "decision"

                accumulated += safe_content

                if ctype not in ("tool_name", "call_arguments"):
                    yield json.dumps(chunk)

                await self._shunt_to_redis_stream(redis, stream_key, chunk)

            if current_block == "fc":
                accumulated += "</fc>"
            elif current_block == "think":
                accumulated += "</think>"

        except Exception as exc:
            LOG.error(f"Stream Exception: {exc}")
            err = {"type": "error", "content": f"Stream error: {exc}", "run_id": run_id}
            yield json.dumps(err)
            await self._shunt_to_redis_stream(redis, stream_key, err)
        finally:
            stop_event.set()

        yield json.dumps({"type": "status", "status": "complete", "run_id": run_id})

        # -------------------------------
        # 2. Parse decision payload
        # -------------------------------
        if decision_buffer:
            try:
                self._decision_payload = json.loads(decision_buffer.strip())
                LOG.info(f"Decision payload validated: {self._decision_payload}")
            except json.JSONDecodeError:
                LOG.warning(f"Failed to parse decision payload: {decision_buffer}")

        yield json.dumps({"type": "status", "status": "processing", "run_id": run_id})

        # -------------------------------
        # 3. Detect and sanitize <fc> blocks
        # -------------------------------
        if "<fc>" in accumulated:
            try:
                fc_pattern = r"<fc>(.*?)</fc>"
                matches = re.findall(fc_pattern, accumulated, re.DOTALL)
                for original_content in matches:
                    if not original_content.strip():
                        continue
                    try:
                        json.loads(original_content)
                        continue
                    except json.JSONDecodeError:
                        pass
                    fix_match = re.match(
                        r"^\s*([a-zA-Z0-9_]+)\s*(\{.*)", original_content, re.DOTALL
                    )
                    if fix_match:
                        func_name = fix_match.group(1)
                        func_args = fix_match.group(2)
                        try:
                            parsed_args, _ = json.JSONDecoder().raw_decode(func_args)
                            valid_payload = json.dumps(
                                {"name": func_name, "arguments": parsed_args}
                            )
                            # REFACTOR: Replace the tagged block with the sanitized tagged block
                            accumulated = accumulated.replace(
                                f"<fc>{original_content}</fc>", f"<fc>{valid_payload}</fc>"
                            )
                        except Exception:
                            pass
            except Exception as e:
                LOG.warning(f"Sanitization warning: {e}")

        has_fc_dict = self.parse_and_set_function_calls(accumulated, assistant_reply)

        message_to_save = assistant_reply
        final_status = StatusEnum.completed.value

        if has_fc_dict:
            final_status = StatusEnum.pending_action.value
            try:
                call_id = f"call_{uuid.uuid4().hex[:8]}"
                self._current_tool_call_id = call_id
                self._pending_tool_payload = has_fc_dict

                tool_calls_structure = [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": has_fc_dict.get("name"),
                            "arguments": json.dumps(has_fc_dict.get("arguments", {})),
                        },
                    }
                ]
                message_to_save = json.dumps(tool_calls_structure)
            except Exception:
                message_to_save = accumulated

        # -------------------------------
        # 4. Save assistant message (Async)
        # -------------------------------
        if message_to_save:
            try:
                # We await the now-asynchronous finalize_conversation
                await asyncio.wait_for(
                    self.finalize_conversation(message_to_save, thread_id, assistant_id, run_id),
                    timeout=20,
                )
            except Exception as e:
                LOG.error(f"finalize_conversation failed for run {run_id}: {e}")

        # -------------------------------
        # 5. Safely update run status (Offloaded to Thread)
        # -------------------------------
        if self.project_david_client:
            try:
                # Since project_david_client is sync, we use to_thread to keep the loop free
                await asyncio.to_thread(
                    self.project_david_client.runs.update_run_status, run_id, final_status
                )
            except Exception as e:
                LOG.error(f"update_run_status failed for run {run_id}: {e}")
        else:
            LOG.warning(
                f"project_david_client is None. Skipping run status update for run {run_id}"
            )

    async def process_conversation(
        self,
        thread_id: str,
        message_id: Optional[str],
        run_id: str,
        assistant_id: str,
        model: Any,
        api_key: Optional[str] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:

        async for chunk in self.stream(
            thread_id,
            message_id,
            run_id,
            assistant_id,
            model,
            api_key=api_key,
            **kwargs,
        ):
            yield chunk

        has_tools = False
        if hasattr(self, "get_function_call_state"):
            has_tools = self.get_function_call_state()

        if has_tools:
            tool_call_id = getattr(self, "_current_tool_call_id", None)
            current_decision = getattr(self, "_decision_payload", None)

            async for chunk in self.process_tool_calls(
                thread_id,
                run_id,
                assistant_id,
                tool_call_id=tool_call_id,
                model=model,
                api_key=api_key,
                decision=current_decision,
            ):
                yield chunk

            if hasattr(self, "set_tool_response_state"):
                self.set_tool_response_state(False)
            if hasattr(self, "set_function_call_state"):
                self.set_function_call_state(None)

            self._current_tool_call_id = None
            self._decision_payload = None

            async for chunk in self.stream(
                thread_id,
                None,
                run_id,
                assistant_id,
                model,
                force_refresh=True,
                api_key=api_key,
                **kwargs,
            ):
                yield chunk
