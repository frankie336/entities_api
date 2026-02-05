from __future__ import annotations

import asyncio
import json
import os
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, Optional

from dotenv import load_dotenv
from projectdavid_common.utilities.logging_service import LoggingUtility
from projectdavid_common.validation import StatusEnum

from entities_api.cache import assistant_cache
from entities_api.cache.assistant_cache import AssistantCache
from entities_api.clients.delta_normalizer import DeltaNormalizer

# --- DEPENDENCIES ---
from src.api.entities_api.dependencies import get_redis, get_redis_sync
from src.api.entities_api.orchestration.engine.orchestrator_core import OrchestratorCore

# --- MIXINS ---
from src.api.entities_api.orchestration.mixins.provider_mixins import _ProviderMixins

load_dotenv()
LOG = LoggingUtility()


class GptOssBaseWorker(
    _ProviderMixins,
    OrchestratorCore,
    ABC,
):
    """
    Async Base for GPT-OSS Providers.
    Corrects Turn 2 latency by terminating consumer tool streams immediately.
    """

    def __init__(
        self,
        *,
        assistant_id: str | None = None,
        thread_id: str | None = None,
        redis=None,
        base_url: str | None = None,
        api_key: str | None = None,
        # assistant_cache: dict | None = None,
        assistant_cache_service: Optional[AssistantCache] = None,
        **extra,
    ) -> None:

        # 2. Setup Redis (Critical for the Mixin fallback)
        # We use get_redis_sync() if no client is provided, ensuring we have a connection.
        self.redis = redis or get_redis_sync()

        # 3. Setup the Cache Service (The "New Way")
        # If passed explicitly, store it. If not, the Mixin will lazy-load it using self.redis
        if assistant_cache_service:
            self._assistant_cache = assistant_cache_service
        elif "assistant_cache" in extra and isinstance(extra["assistant_cache"], AssistantCache):
            # Handle case where it might be passed via **extra
            self._assistant_cache = extra["assistant_cache"]

        # 4. Setup the Data/Config (The "Old Way" renamed)
        # We rename this to avoid overwriting the Mixin's property.
        # We check if a raw dict was passed in 'extra' (legacy support)
        legacy_config = extra.get("assistant_config") or extra.get("assistant_cache")
        self.assistant_config: Dict[str, Any] = (
            legacy_config if isinstance(legacy_config, dict) else {}
        )

        self._david_client: Any = None

        self.redis = redis or get_redis()
        self.assistant_id = assistant_id
        self.thread_id = thread_id
        self.base_url = base_url or os.getenv("BASE_URL")
        self.api_key = api_key

        self.model_name = extra.get("model_name", "openai/gpt-oss-120b")
        self.max_context_window = extra.get("max_context_window", 131072)
        self.threshold_percentage = extra.get("threshold_percentage", 0.8)

        self._current_tool_call_id: str | None = None
        self._pending_tool_payload: Optional[Dict[str, Any]] = None
        self._decision_payload: Optional[Dict[str, Any]] = None

        self.setup_services()

        if not hasattr(self, "get_function_call_state"):
            LOG.error("CRITICAL: ToolRoutingMixin failed to load.")
            self.get_function_call_state = lambda: None
            self.set_function_call_state = lambda x: None
            self.set_tool_response_state = lambda x: None

    @abstractmethod
    def _get_client_instance(self, api_key: str):
        pass

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
        import re
        import uuid

        redis = self.redis
        stream_key = f"stream:{run_id}"
        stop_event = self.start_cancellation_monitor(run_id)

        self._current_tool_call_id = None
        self._pending_tool_payload = None
        self._decision_payload = None

        accumulated: str = ""
        assistant_reply: str = ""
        reasoning_reply: str = ""
        decision_buffer: str = ""
        plan_buffer: str = ""
        current_block: str | None = None

        try:
            if hasattr(self, "_get_model_map") and (mapped := self._get_model_map(model)):
                model = mapped

            self.assistant_id = assistant_id
            # [NEW] Ensure cache is hot before starting
            await self._ensure_config_loaded()
            agent_mode_setting = self.assistant_config.get("agent_mode", False)
            decision_telemetry = self.assistant_config.get("decision_telemetry", True)

            raw_ctx = await self._set_up_context_window(
                assistant_id,
                thread_id,
                trunk=True,
                structured_tool_call=True,
                force_refresh=force_refresh,
                agent_mode=agent_mode_setting,
                decision_telemetry=decision_telemetry,
            )
            cleaned_ctx, extracted_tools = self.prepare_native_tool_context(raw_ctx)

            if not api_key:
                yield json.dumps({"type": "error", "content": "Missing API key."})
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

            async for chunk in DeltaNormalizer.async_iter_deltas(raw_stream, run_id):
                if stop_event.is_set():
                    break

                ctype = chunk.get("type")
                ccontent = chunk.get("content") or ""
                safe_content = ccontent if isinstance(ccontent, str) else ""

                if ctype == "content":
                    if current_block == "fc":
                        accumulated += "</fc>"
                    elif current_block == "think":
                        accumulated += "</think>"
                    elif current_block == "plan":
                        accumulated += "</plan>"
                    current_block = None
                    assistant_reply += ccontent
                    accumulated += ccontent
                elif ctype == "call_arguments":
                    if current_block != "fc":
                        if current_block == "think":
                            accumulated += "</think>"
                        elif current_block == "plan":
                            accumulated += "</plan>"
                        accumulated += "<fc>"
                        current_block = "fc"
                    accumulated += ccontent
                elif ctype == "reasoning":
                    if current_block != "think":
                        if current_block == "fc":
                            accumulated += "</fc>"
                        elif current_block == "plan":
                            accumulated += "</plan>"
                        accumulated += "<think>"
                        current_block = "think"
                    reasoning_reply += ccontent
                elif ctype == "plan":
                    if current_block != "plan":
                        if current_block == "fc":
                            accumulated += "</fc>"
                        elif current_block == "think":
                            accumulated += "</think>"
                        accumulated += "<plan>"
                        current_block = "plan"
                    plan_buffer += ccontent
                    accumulated += ccontent
                elif ctype == "decision":
                    decision_buffer += ccontent
                    if current_block == "fc":
                        accumulated += "</fc>"
                    elif current_block == "think":
                        accumulated += "</think>"
                    elif current_block == "plan":
                        accumulated += "</plan>"
                    current_block = "decision"

                if ctype == "call_arguments":
                    continue
                yield json.dumps(chunk)
                await self._shunt_to_redis_stream(redis, stream_key, chunk)

            if current_block == "fc":
                accumulated += "</fc>"
            elif current_block == "think":
                accumulated += "</think>"
            elif current_block == "plan":
                accumulated += "</plan>"

        except Exception as exc:
            LOG.error(f"DEBUG: Stream Exception: {exc}")
            err = {"type": "error", "content": f"Stream error: {exc}", "run_id": run_id}
            yield json.dumps(err)
            await self._shunt_to_redis_stream(redis, stream_key, err)
        finally:
            stop_event.set()

        yield json.dumps({"type": "status", "status": "complete", "run_id": run_id})

        # --- SYNC-REPLICA 2: Validate Decision Payload ---
        if decision_buffer:
            try:
                self._decision_payload = json.loads(decision_buffer.strip())
                LOG.info(f"Decision payload validated: {self._decision_payload}")
            except Exception as e:
                LOG.error(f"Failed to parse decision payload: {e}")

        # Keep-Alive Heartbeat
        yield json.dumps({"type": "status", "status": "processing", "run_id": run_id})

        # --- SYNC-REPLICA 3: Post-Stream Sanitization ---
        if "<fc>" in accumulated:
            try:
                fc_pattern = r"<fc>(.*?)</fc>"
                matches = re.findall(fc_pattern, accumulated, re.DOTALL)
                for original_content in matches:
                    try:
                        json.loads(original_content)
                        continue
                    except json.JSONDecodeError:
                        pass

                    fix_match = re.match(
                        r"^\s*([a-zA-Z0-9_]+)\s*(\{.*)", original_content, re.DOTALL
                    )
                    if fix_match:
                        func_name, func_args = fix_match.group(1), fix_match.group(2)
                        try:
                            parsed_args, _ = json.JSONDecoder().raw_decode(func_args)
                            valid_payload = json.dumps(
                                {"name": func_name, "arguments": parsed_args}
                            )
                            accumulated = accumulated.replace(
                                f"<fc>{original_content}</fc>",
                                f"<fc>{valid_payload}</fc>",
                            )
                        except:
                            pass
            except Exception as e:
                LOG.error(f"Error during tool call sanitization: {e}")

        tool_calls_batch = self.parse_and_set_function_calls(accumulated, assistant_reply)
        message_to_save = assistant_reply
        final_status = StatusEnum.completed.value

        # --- SYNC-REPLICA 5: Structure and Override Save Message ---
        if tool_calls_batch:
            # 1. Update the internal queue for the dispatcher (process_tool_calls)
            self._tool_queue = tool_calls_batch
            final_status = StatusEnum.pending_action.value

            # 2. Build the Hermes/OpenAI Structured Envelope for the Dialogue
            # This is what makes Turn 2 contextually consistent.
            tool_calls_structure = []
            for tool in tool_calls_batch:
                tool_id = tool.get("id") or f"call_{uuid.uuid4().hex[:8]}"

                tool_calls_structure.append(
                    {
                        "id": tool_id,
                        "type": "function",
                        "function": {
                            "name": tool.get("name"),
                            "arguments": (
                                json.dumps(tool.get("arguments", {}))
                                if isinstance(tool.get("arguments"), dict)
                                else tool.get("arguments")
                            ),
                        },
                    }
                )

            # CRITICAL: We overwrite message_to_save with the standard tool structure
            message_to_save = json.dumps(tool_calls_structure)

            # [LOGGING] Verify ID Parity
            LOG.info(f"\n🚀 [L3 AGENT MANIFEST] Turn 1 Batch of {len(tool_calls_structure)}")
            for item in tool_calls_structure:
                LOG.info(f"   ▸ Tool: {item['function']['name']} | ID: {item['id']}")

        # Persistence: Assistant Plan/Actions saved to Thread
        if message_to_save:
            await self.finalize_conversation(message_to_save, thread_id, assistant_id, run_id)

        # Update Run status to trigger Dispatch Turn
        if self.project_david_client:
            await asyncio.to_thread(
                self.project_david_client.runs.update_run_status, run_id, final_status
            )

        if not tool_calls_batch:
            yield json.dumps({"type": "status", "status": "complete", "run_id": run_id})
