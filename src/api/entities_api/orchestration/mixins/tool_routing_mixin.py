# src/api/entities_api/orchestration/mixins/tool_routing_mixin.py
"""
High-level routing of <fc> tool-calls with detailed activation logs.

Responsibilities
----------------
• detect & validate <fc>{…}</fc> JSON blocks OR raw JSON payloads
• flip internal flags so only ONE handler runs
• dispatch to either platform-native or consumer handlers
"""

from __future__ import annotations

import re
from typing import Dict, Optional

from src.api.entities_api.constants.assistant import PLATFORM_TOOLS
from src.api.entities_api.constants.platform import SPECIAL_CASE_TOOL_HANDLING
from src.api.entities_api.services.logging_service import LoggingUtility

LOG = LoggingUtility()


class ToolRoutingMixin:
    FC_REGEX = re.compile("<fc>\\s*(?P<payload>\\{.*?\\})\\s*</fc>", re.DOTALL | re.I)
    _tool_response: bool = False
    _function_call: Optional[Dict] = None

    def set_tool_response_state(self, value: bool) -> None:
        LOG.debug("TOOL-ROUTER ▸ set_tool_response_state(%s)", value)
        self._tool_response = value

    def get_tool_response_state(self) -> bool:
        return self._tool_response

    def set_function_call_state(self, value: Optional[Dict] = None) -> None:
        """
        Store the queued function-call payload, or pass None to clear it.
        """
        LOG.debug("TOOL-ROUTER ▸ set_function_call_state(%s)", value)
        self._function_call = value

    def get_function_call_state(self) -> Optional[Dict]:
        return self._function_call

    def parse_and_set_function_calls(
        self, accumulated_content: str, assistant_reply: str
    ) -> Optional[Dict]:
        """
        Robustly locate a function call payload.
        Strategy 1: Look for <fc>{JSON}</fc> tags (DeepSeek / Channel style).
        Strategy 2: Look for Raw JSON (Native Llama/GPT-OSS style).
        """
        from src.api.entities_api.orchestration.mixins.json_utils_mixin import \
            JsonUtilsMixin

        if not isinstance(self, JsonUtilsMixin):
            raise TypeError("ToolRoutingMixin must be mixed with JsonUtilsMixin")

        def _validate_payload(json_dict: Dict) -> bool:
            """Check if dict conforms to function call schema."""
            if self.is_valid_function_call_response(
                json_dict
            ) or self.is_complex_vector_search(json_dict):
                return True
            return False

        def _extract_json_block(text: str) -> Optional[Dict]:
            # 1. Try Regex Tag Extraction
            m = self.FC_REGEX.search(text)
            if m:
                raw_json = m.group("payload")
                LOG.debug("FC-SCAN ▸ found <fc> tag content")
                parsed = self.ensure_valid_json(raw_json)
                if parsed and _validate_payload(parsed):
                    LOG.debug("FC-SCAN ✓ valid <fc> func-call: %s", parsed)
                    return parsed
                LOG.debug("FC-SCAN ✗ <fc> content invalid JSON or schema")

            # 2. Try Raw JSON parsing (for Native Tool Call accumulation)
            # Only try this if the text starts/ends like a JSON object to avoid perf hit
            stripped = text.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                parsed = self.ensure_valid_json(stripped)
                if parsed and _validate_payload(parsed):
                    LOG.debug("FC-SCAN ✓ valid raw JSON func-call: %s", parsed)
                    return parsed

            return None

        # A. Check Accumulated Content (Primary source for Native/Streamed calls)
        parsed_fc = _extract_json_block(accumulated_content)
        if parsed_fc:
            self.set_tool_response_state(True)
            self.set_function_call_state(parsed_fc)
            return parsed_fc

        # B. Check Assistant Reply (Primary source for Text-based calls)
        parsed_fc = _extract_json_block(assistant_reply)
        if parsed_fc and (not self.get_tool_response_state()):
            self.set_tool_response_state(True)
            self.set_function_call_state(parsed_fc)
            return parsed_fc

        # C. Fallback: Loose extraction from text body
        loose = self.extract_function_calls_within_body_of_text(assistant_reply)
        if loose:
            LOG.debug("FC-SCAN ✓ legacy pattern: %s", loose[0])
            self.set_tool_response_state(True)
            self.set_function_call_state(loose[0])
            return loose[0]

        LOG.debug("FC-SCAN ✗ nothing found")
        return None

    def process_function_calls(
        self,
        thread_id: str,
        run_id: str,
        assistant_id: str,
        *,
        model: str | None = None,
        api_key: str | None = None,
    ):
        """
        Delegates to the correct concrete handler.

        • platform specials (code_interpreter / computer / file_search)
          are invoked directly **without** the extra api_key argument
        • classical platform tools -> `_process_platform_tool_calls`
        • consumer tools           -> `_process_tool_calls` (gets api_key)
        """
        fc = self.get_function_call_state()
        if not fc:
            LOG.debug("TOOL-ROUTER ▸ no queued call – noop")
            return
        name = fc.get("name")
        args = fc.get("arguments", {})
        LOG.info("TOOL-ROUTER ▶ dispatching tool=%s args=%s", name, args)
        if name == "code_interpreter":
            LOG.debug("TOOL-ROUTER ▸ route → handle_code_interpreter_action")
            yield from self.handle_code_interpreter_action(
                thread_id=thread_id,
                run_id=run_id,
                assistant_id=assistant_id,
                arguments_dict=args,
            )
            return
        if name == "computer":
            LOG.debug("TOOL-ROUTER ▸ route → handle_shell_action")
            yield from self.handle_shell_action(
                thread_id=thread_id,
                run_id=run_id,
                assistant_id=assistant_id,
                arguments_dict=args,
            )
            return
        if name == "file_search":
            LOG.debug("TOOL-ROUTER ▸ route → _handle_file_search")
            self.handle_file_search(
                thread_id=thread_id,
                run_id=run_id,
                assistant_id=assistant_id,
                arguments_dict=args,
            )
            return
        if name in PLATFORM_TOOLS:
            if name in SPECIAL_CASE_TOOL_HANDLING:
                LOG.debug("TOOL-ROUTER ▸ platform special-case → _process_tool_calls")
                self._process_tool_calls(
                    thread_id, assistant_id, fc, run_id, api_key=api_key
                )
            else:
                LOG.debug(
                    "TOOL-ROUTER ▸ platform native → _process_platform_tool_calls"
                )
                self._process_platform_tool_calls(thread_id, assistant_id, fc, run_id)
        else:
            LOG.debug("TOOL-ROUTER ▸ consumer tool → _process_tool_calls")
            self._process_tool_calls(
                thread_id, assistant_id, fc, run_id, api_key=api_key
            )
