# src/api/entities_api/orchestration/mixins/tool_routing_mixin.py

from __future__ import annotations

import inspect
import json
import re
from typing import AsyncGenerator, Dict, Optional, List, Union

from src.api.entities_api.constants.assistant import PLATFORM_TOOLS
from src.api.entities_api.constants.platform import SPECIAL_CASE_TOOL_HANDLING
from src.api.entities_api.services.logging_service import LoggingUtility

LOG = LoggingUtility()


class ToolRoutingMixin:
    """
    High-level routing of tool-calls.
    Refactored for Level 2 Reliability: Platform tools (Code, Computer, File Search)
    now support automated internal self-correction turns.
    """

    # UPDATED: Regex for global finding
    FC_REGEX = re.compile(r"<fc>\s*(?P<payload>\{.*?\})\s*</fc>", re.DOTALL | re.I)

    _tool_response: bool = False
    _function_calls: List[Dict] = []  # [L3] Changed to a list for batching

    # -----------------------------------------------------
    # State Management
    # -----------------------------------------------------
    def set_tool_response_state(self, value: bool) -> None:
        LOG.debug("TOOL-ROUTER ▸ set_tool_response_state(%s)", value)
        self._tool_response = value

    # -----------------------------------------------------
    # Helper: Moved to Class Scope for L3 Batching
    # -----------------------------------------------------

    def _normalize_arguments(self, payload: Dict) -> Dict:
        """Heals stringified JSON arguments in a tool payload."""
        args = payload.get("arguments")
        if isinstance(args, str):
            try:
                clean_args = args.strip()
                if clean_args.startswith("```"):
                    clean_args = clean_args.strip("`").replace("json", "").strip()
                payload["arguments"] = json.loads(clean_args)
            except Exception:
                LOG.warning("TOOL-ROUTER ▸ failed to parse string arguments")
        return payload

        # -----------------------------------------------------
        # State Management
        # -----------------------------------------------------

    def set_function_call_state(self, value: Optional[Union[Dict, List[Dict]]] = None) -> None:
        if value is None:
            self._function_calls = []
        elif isinstance(value, dict):
            self._function_calls = [value]
        else:
            self._function_calls = value

    def get_function_call_state(self) -> List[Dict]:
        return self._function_calls

        # -----------------------------------------------------
        # The Pedantic L3 Parser
        # -----------------------------------------------------

    def parse_and_set_function_calls(
        self, accumulated_content: str, assistant_reply: str
    ) -> List[Dict]:
        """
        Scans text for tool call payloads.
        Level 3: Isolates planning blocks and extracts ALL tool tags in sequence.
        """
        from src.api.entities_api.orchestration.mixins.json_utils_mixin import JsonUtilsMixin

        if not isinstance(self, JsonUtilsMixin):
            raise TypeError("ToolRoutingMixin must be mixed with JsonUtilsMixin")

        # --- STEP 1: PLAN ISOLATION ---
        # We strip the plan block so that if the model says:
        # "I will call <fc>{...}</fc>" in its reasoning, it's ignored.
        # We only care about tags appearing AFTER or OUTSIDE the plan.
        body_to_scan = re.sub(r"<plan>.*?</plan>", "", accumulated_content, flags=re.DOTALL)

        # --- STEP 2: MULTI-TAG EXTRACTION ---
        matches = self.FC_REGEX.finditer(body_to_scan)
        results = []

        for m in matches:
            raw_payload = m.group("payload")
            # ensure_valid_json lives on JsonUtilsMixin
            parsed = self.ensure_valid_json(raw_payload)
            if parsed:
                # Call the now-available class method
                normalized = self._normalize_arguments(parsed)
                results.append(normalized)

        if results:
            LOG.info(f"L3-PARSER ▸ Successfully parsed {len(results)} tool(s) in batch.")
            self.set_tool_response_state(True)
            self.set_function_call_state(results)
            return results

        # --- STEP 3: LEGACY FALLBACK ---
        # (Only if no tags were found at all)
        loose = self.extract_function_calls_within_body_of_text(assistant_reply)
        if loose:
            normalized = [self._normalize_arguments(l) for l in loose]
            self.set_tool_response_state(True)
            self.set_function_call_state(normalized)
            return normalized

        LOG.debug("L3-PARSER ✗ No tool calls detected.")
        return []

    # -----------------------------------------------------
    # Async Helpers
    # -----------------------------------------------------
    async def _yield_maybe_async(self, obj):
        """Helper to yield from sync generators, async generators, or coroutines."""
        if obj is None:
            return
        if inspect.isasyncgen(obj):
            async for chunk in obj:
                yield chunk
        elif inspect.isgenerator(obj):
            for chunk in obj:
                yield chunk
        elif inspect.iscoroutine(obj):
            result = await obj
            if result:
                yield result

    # -----------------------------------------------------
    # Tool Processing & Dispatching (Level 3 Batch Enabled)
    # -----------------------------------------------------
    async def process_tool_calls(
        self,
        thread_id: str,
        run_id: str,
        assistant_id: str,
        tool_call_id: Optional[str] = None,
        *,
        model: str | None = None,
        api_key: str | None = None,
        decision: Optional[Dict] = None,
    ) -> AsyncGenerator:
        """
        Orchestrates the execution of one or more detected tool calls.
        Level 3: Iterates through the batch queue, supporting parallel intent.
        """
        # Retrieve the batch queue from state (now a List[Dict])
        batch = self.get_function_call_state()
        if not batch:
            LOG.warning("TOOL-ROUTER ▸ Dispatcher called but no tool calls found in state.")
            return

        LOG.info("TOOL-ROUTER ▸ Processing batch of %s tool calls.", len(batch))

        for fc in batch:
            name = fc.get("name")
            args = fc.get("arguments")

            # --- LEVEL 2 HEALING (Localized to batch item) ---
            if not name and decision:
                inferred_name = (
                    decision.get("tool") or decision.get("function") or decision.get("name")
                )
                if inferred_name:
                    LOG.info(
                        "TOOL-ROUTER ▸ Healing batch item using decision tool='%s'",
                        inferred_name,
                    )
                    name = inferred_name
                    if args is None:
                        args = fc

            if not name:
                LOG.error("TOOL-ROUTER ▸ Failed to resolve name for tool call: %s", fc)
                continue

            LOG.info("TOOL-ROUTER ▶ dispatching batch item: tool=%s", name)

            # -----------------------------------------------------
            # 1. PLATFORM TOOLS (Direct Execution)
            # -----------------------------------------------------
            if name == "code_interpreter":
                async for chunk in self._yield_maybe_async(
                    self.handle_code_interpreter_action(
                        thread_id=thread_id,
                        run_id=run_id,
                        assistant_id=assistant_id,
                        arguments_dict=args,
                        tool_call_id=tool_call_id,
                        decision=decision,
                    )
                ):
                    yield chunk

            elif name == "computer":
                async for chunk in self._yield_maybe_async(
                    self.handle_shell_action(
                        thread_id=thread_id,
                        run_id=run_id,
                        assistant_id=assistant_id,
                        arguments_dict=args,
                        tool_call_id=tool_call_id,
                        decision=decision,
                    )
                ):
                    yield chunk

            elif name == "file_search":
                # Note: handle_file_search handles its own submit_tool_output internally
                await self._yield_maybe_async(
                    self.handle_file_search(
                        thread_id=thread_id,
                        run_id=run_id,
                        assistant_id=assistant_id,
                        arguments_dict=args,
                        tool_call_id=tool_call_id,
                        decision=decision,
                    )
                )

            # -----------------------------------------------------
            # 2. OTHER PLATFORM / SYSTEM TOOLS
            # -----------------------------------------------------
            elif name in PLATFORM_TOOLS:
                if name in SPECIAL_CASE_TOOL_HANDLING:
                    gen = self._process_tool_calls(
                        thread_id=thread_id,
                        assistant_id=assistant_id,
                        content=fc,
                        run_id=run_id,
                        tool_call_id=tool_call_id,
                        api_key=api_key,
                        decision=decision,
                    )
                else:
                    gen = self._process_platform_tool_calls(
                        thread_id=thread_id,
                        assistant_id=assistant_id,
                        content=fc,
                        run_id=run_id,
                        tool_call_id=tool_call_id,
                        decision=decision,
                    )
                async for chunk in self._yield_maybe_async(gen):
                    yield chunk

            # -----------------------------------------------------
            # 3. CONSUMER TOOLS (SDK Manifest)
            # -----------------------------------------------------
            else:
                # We reuse _process_tool_calls to emit individual manifests
                # but ensure the loop in stream() manages the final 'pending_action' state.
                async for chunk in self._yield_maybe_async(
                    self._process_tool_calls(
                        thread_id=thread_id,
                        assistant_id=assistant_id,
                        content=fc,
                        run_id=run_id,
                        tool_call_id=tool_call_id,
                        api_key=api_key,
                        decision=decision,
                    )
                ):
                    yield chunk

        LOG.info("TOOL-ROUTER ▸ Batch dispatch complete.")
