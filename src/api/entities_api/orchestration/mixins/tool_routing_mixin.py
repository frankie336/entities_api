"""
High-level routing of <fc> tool-calls with detailed activation logs.
"""

from __future__ import annotations

import json
import re
from typing import Dict, Optional

from src.api.entities_api.constants.assistant import PLATFORM_TOOLS
from src.api.entities_api.constants.platform import SPECIAL_CASE_TOOL_HANDLING
from src.api.entities_api.services.logging_service import LoggingUtility

LOG = LoggingUtility()


class ToolRoutingMixin:
    FC_REGEX = re.compile(r"<fc>\s*(?P<payload>\{.*?\})\s*</fc>", re.DOTALL | re.I)
    _tool_response: bool = False
    _function_call: Optional[Dict] = None

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

    def parse_and_set_function_calls(
        self, accumulated_content: str, assistant_reply: str
    ) -> Optional[Dict]:
        """
        Robustly locate a function call payload.
        """
        from src.api.entities_api.orchestration.mixins.json_utils_mixin import (
            JsonUtilsMixin,
        )

        if not isinstance(self, JsonUtilsMixin):
            raise TypeError("ToolRoutingMixin must be mixed with JsonUtilsMixin")

        def _validate_payload(json_dict: Dict) -> bool:
            if self.is_valid_function_call_response(
                json_dict
            ) or self.is_complex_vector_search(json_dict):
                return True
            return False

        def _normalize_arguments(payload: Dict) -> Dict:
            """
            Ensure 'arguments' is a Dictionary.
            """
            args = payload.get("arguments")
            if isinstance(args, str):
                try:
                    # Clean potential markdown or whitespace
                    clean_args = args.strip()
                    if clean_args.startswith("```"):
                        clean_args = clean_args.strip("`").replace("json", "").strip()

                    payload["arguments"] = json.loads(clean_args)
                except (json.JSONDecodeError, TypeError):
                    LOG.warning(
                        "TOOL-ROUTER ▸ failed to parse string arguments: %s", args
                    )
                    pass
            return payload

        def _extract_json_block(text: str) -> Optional[Dict]:
            if not text:
                return None

            # 1. Try Regex Tag Extraction
            m = self.FC_REGEX.search(text)
            if m:
                raw_json = m.group("payload")
                parsed = self.ensure_valid_json(raw_json)
                if parsed and _validate_payload(parsed):
                    LOG.debug("FC-SCAN ✓ valid <fc> func-call")
                    return _normalize_arguments(parsed)

            # 2. Try Raw JSON Extraction (Robust Finder)
            start_idx = text.find("{")
            end_idx = text.rfind("}")

            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                candidate = text[start_idx : end_idx + 1]
                try:
                    parsed = self.ensure_valid_json(candidate)
                    if parsed and _validate_payload(parsed):
                        LOG.debug("FC-SCAN ✓ valid JSON func-call found in text")
                        return _normalize_arguments(parsed)
                except Exception:
                    pass

            return None

        # A. Check Accumulated Content (Primary)
        parsed_fc = _extract_json_block(accumulated_content)
        if parsed_fc:
            self.set_tool_response_state(True)
            self.set_function_call_state(parsed_fc)
            return parsed_fc

        # B. Check Assistant Reply (Fallback)
        parsed_fc = _extract_json_block(assistant_reply)
        if parsed_fc and (not self.get_tool_response_state()):
            self.set_tool_response_state(True)
            self.set_function_call_state(parsed_fc)
            return parsed_fc

        # C. Fallback: Loose extraction
        loose = self.extract_function_calls_within_body_of_text(assistant_reply)
        if loose:
            LOG.debug("FC-SCAN ✓ legacy pattern found")
            normalized = _normalize_arguments(loose[0])
            self.set_tool_response_state(True)
            self.set_function_call_state(normalized)
            return normalized

        LOG.debug("FC-SCAN ✗ nothing found")
        return None

    def process_tool_calls(
        self,
        thread_id: str,
        run_id: str,
        assistant_id: str,
        tool_call_id: Optional[str] = None,
        *,
        model: str | None = None,
        api_key: str | None = None,
    ):
        fc = self.get_function_call_state()
        if not fc:
            LOG.debug("TOOL-ROUTER ▸ no queued call – noop")
            return

        name = fc.get("name")
        args = fc.get("arguments", {})

        if args is None:
            args = {}

        LOG.info("TOOL-ROUTER ▶ dispatching tool=%s", name)

        # --------------------------------------------------
        # Handles code code_interpreter calls, and returns
        # --------------------------------------------------
        if name == "code_interpreter":
            yield from self.handle_code_interpreter_action(
                thread_id=thread_id,
                run_id=run_id,
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                arguments_dict=args,
            )
            return

        if name == "computer":
            yield from self.handle_shell_action(
                thread_id=thread_id,
                run_id=run_id,
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                arguments_dict=args,
            )
            return
        if name == "file_search":
            self.handle_file_search(
                thread_id=thread_id,
                run_id=run_id,
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                arguments_dict=args,
            )
            return

        if name in PLATFORM_TOOLS:
            if name in SPECIAL_CASE_TOOL_HANDLING:
                self._process_tool_calls(
                    thread_id, assistant_id, fc, run_id, api_key=api_key
                )
            else:
                self._process_platform_tool_calls(thread_id, assistant_id, fc, run_id)
        else:
            self._process_tool_calls(
                thread_id,
                assistant_id,
                fc,
                run_id,
                tool_call_id=tool_call_id,
                api_key=api_key,
            )
