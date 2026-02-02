"""
High-level routing of <fc> tool-calls with detailed activation logs.
(Async Version - Restored Decision/Flat Payload Handling)
"""

from __future__ import annotations

import inspect
import json
import re
from typing import AsyncGenerator, Dict, Optional

from src.api.entities_api.constants.assistant import PLATFORM_TOOLS
from src.api.entities_api.constants.platform import SPECIAL_CASE_TOOL_HANDLING
from src.api.entities_api.services.logging_service import LoggingUtility

LOG = LoggingUtility()


class ToolRoutingMixin:
    FC_REGEX = re.compile(r"<fc>\s*(?P<payload>\{.*?\})\s*</fc>", re.DOTALL | re.I)
    _tool_response: bool = False
    _function_call: Optional[Dict] = None

    # -----------------------------------------------------
    # State Management
    # -----------------------------------------------------
    def set_tool_response_state(self, value: bool) -> None:
        LOG.debug("TOOL-ROUTER ▸ set_tool_response_state(%s)", value)
        self._tool_response = value

    def get_tool_response_state(self) -> bool:
        return self._tool_response

    def set_function_call_state(self, value: Optional[Dict] = None) -> None:
        LOG.debug("TOOL-ROUTER ▸ set_function_call_state(%s)", value)
        self._function_call = value

    def get_function_call_state(self) -> Optional[Dict]:
        return self._function_call

    # -----------------------------------------------------
    # Parsing Logic
    # -----------------------------------------------------

    def parse_and_set_function_calls(
        self, accumulated_content: str, assistant_reply: str
    ) -> Optional[Dict]:
        """
        Scans text for tool call payloads, supporting both <fc> tags and raw JSON.
        Returns the parsed dictionary and sets internal state.
        """
        from src.api.entities_api.orchestration.mixins.json_utils_mixin import JsonUtilsMixin

        if not isinstance(self, JsonUtilsMixin):
            raise TypeError("ToolRoutingMixin must be mixed with JsonUtilsMixin")

        def _normalize_arguments(payload: Dict) -> Dict:
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

        def _extract_json_block(text: str) -> Optional[Dict]:
            if not text:
                return None

            # 1. Try explicit <fc> tags
            m = self.FC_REGEX.search(text)
            if m:
                parsed = self.ensure_valid_json(m.group("payload"))
                if parsed:
                    # Healing: We accept even if 'name' is missing,
                    # relying on 'decision' telemetry in process_tool_calls.
                    LOG.debug("FC-SCAN ✓ found JSON in <fc> tags")
                    return _normalize_arguments(parsed)

            # 2. Try raw JSON finding (Searching for { ... })
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                candidate = text[start : end + 1]
                parsed = self.ensure_valid_json(candidate)
                if parsed:
                    LOG.debug("FC-SCAN ✓ found raw JSON block")
                    return _normalize_arguments(parsed)

            return None

        # Check accumulated content (streaming buffer) or final reply
        parsed_fc = _extract_json_block(accumulated_content) or _extract_json_block(assistant_reply)

        if parsed_fc:
            self.set_tool_response_state(True)
            self.set_function_call_state(parsed_fc)
            return parsed_fc

        # Legacy fallback for older formatting
        loose = self.extract_function_calls_within_body_of_text(assistant_reply)
        if loose:
            normalized = _normalize_arguments(loose[0])
            self.set_tool_response_state(True)
            self.set_function_call_state(normalized)
            return normalized

        LOG.debug("FC-SCAN ✗ nothing found")
        return None

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
    # Tool Processing & Dispatching
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
        Orchestrates the execution of a detected tool call.
        """
        fc = self.get_function_call_state()
        if not fc:
            return

        name = fc.get("name")
        args = fc.get("arguments")

        # --- HEALING LOGIC (Recovery for flat payloads) ---
        if not name and decision:
            inferred_name = decision.get("tool") or decision.get("function") or decision.get("name")
            if inferred_name:
                LOG.info(
                    "TOOL-ROUTER ▸ Healing flat payload using decision tool='%s'",
                    inferred_name,
                )
                name = inferred_name
                if args is None:
                    args = fc  # If no arguments key, the whole payload is the arguments
                fc = {"name": name, "arguments": args}
                self.set_function_call_state(fc)

        if not name:
            LOG.error(
                "TOOL-ROUTER ▸ Failed to resolve tool name. Payload: %s, Decision: %s",
                fc,
                decision,
            )
            return

        LOG.info("TOOL-ROUTER ▶ dispatching tool=%s", name)

        # -----------------------------------------------------
        # DISPATCHING WITH KEYWORD ARGUMENTS
        # -----------------------------------------------------

        # 1. Code Interpreter
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

        # 2. Computer / Shell
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

        # 3. File Search
        elif name == "file_search":
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

        # 4. Platform Tools
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

        # 5. Default Consumer Tools
        else:
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
