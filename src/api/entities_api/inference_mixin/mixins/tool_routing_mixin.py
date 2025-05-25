"""
High-level routing of <fc> tool-calls with detailed activation logs.

Responsibilities
----------------
• detect & validate <fc>{…}</fc> JSON blocks
• flip internal flags so only ONE handler runs
• dispatch to either platform-native or consumer handlers
"""

from __future__ import annotations

import re
from typing import Dict, Optional

from entities_api.constants.assistant import PLATFORM_TOOLS
from entities_api.constants.platform import SPECIAL_CASE_TOOL_HANDLING
from entities_api.services.logging_service import LoggingUtility

LOG = LoggingUtility()


class ToolRoutingMixin:
    # fast regex to spot a complete <fc>{…}</fc> block in the stream
    FC_REGEX = re.compile(r"<fc>\s*(?P<payload>\{.*?\})\s*</fc>", re.DOTALL | re.I)

    # ------------------------------------------------------------------ #
    # simple flags                                                       #
    # ------------------------------------------------------------------ #
    _tool_response: bool = False
    _function_call: Optional[Dict] = None

    def set_tool_response_state(self, value: bool) -> None:
        LOG.debug("TOOL-ROUTER ▸ set_tool_response_state(%s)", value)
        self._tool_response = value

    def get_tool_response_state(self) -> bool:
        return self._tool_response

    def set_function_call_state(self, value: Dict) -> None:
        LOG.debug("TOOL-ROUTER ▸ set_function_call_state(%s)", value)
        self._function_call = value

    def get_function_call_state(self) -> Optional[Dict]:
        return self._function_call

    # ------------------------------------------------------------------ #
    # 1️⃣  Detect function-call blocks                                    #
    # ------------------------------------------------------------------ #
    def parse_and_set_function_calls(
        self, accumulated_content: str, assistant_reply: str
    ) -> Optional[Dict]:
        """
        Robustly locate a <fc>{...}</fc> JSON block *anywhere* in either
        accumulated_content or assistant_reply, even if split across chunks.
        """

        from .json_utils_mixin import \
            JsonUtilsMixin  # local import – avoid cycle

        if not isinstance(self, JsonUtilsMixin):  # type: ignore
            raise TypeError("ToolRoutingMixin must be mixed with JsonUtilsMixin")

        def _extract_json_block(text: str) -> Optional[Dict]:
            m = self.FC_REGEX.search(text)
            if not m:
                LOG.debug("FC-SCAN ▸ no tag in %r …", text[-120:])
                return None

            raw_json = m.group("payload")
            LOG.debug("FC-SCAN ▸ candidate JSON: %s", raw_json)

            parsed = self.ensure_valid_json(raw_json)  # normalises quotes, commas
            if not parsed:
                LOG.debug("FC-SCAN ✗ invalid JSON → rejected")
                return None

            if self.is_valid_function_call_response(
                parsed
            ) or self.is_complex_vector_search(parsed):
                LOG.debug("FC-SCAN ✓ valid func-call: %s", parsed)
                return parsed

            LOG.debug("FC-SCAN ✗ schema mismatch → rejected")
            return None

        # ① accumulated stream (handles split tags)
        parsed_fc = _extract_json_block(accumulated_content)
        if parsed_fc:
            self.set_tool_response_state(True)
            self.set_function_call_state(parsed_fc)
            return parsed_fc

        # ② full assistant reply (legacy models put tags at the end)
        parsed_fc = _extract_json_block(assistant_reply)
        if parsed_fc and not self.get_tool_response_state():
            self.set_tool_response_state(True)
            self.set_function_call_state(parsed_fc)
            return parsed_fc

        # ③ heuristic fallback – JSON without <fc> wrappers
        loose = self.extract_function_calls_within_body_of_text(
            assistant_reply
        )  # type: ignore[attr-defined]
        if loose:
            LOG.debug("FC-SCAN ✓ legacy pattern: %s", loose[0])
            self.set_tool_response_state(True)
            self.set_function_call_state(loose[0])
            return loose[0]

        LOG.debug("FC-SCAN ✗ nothing found")
        return None

    # ------------------------------------------------------------------ #
    # 2️⃣  Dispatch                                                       #
    # ------------------------------------------------------------------ #
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

        # ---- platform specials -----------------------------------------
        if name == "code_interpreter":
            LOG.debug("TOOL-ROUTER ▸ route → handle_code_interpreter_action")
            yield from self.handle_code_interpreter_action(  # type: ignore
                thread_id=thread_id,
                run_id=run_id,
                assistant_id=assistant_id,
                arguments_dict=args,
            )
            return

        if name == "computer":
            LOG.debug("TOOL-ROUTER ▸ route → handle_shell_action")
            yield from self.handle_shell_action(  # type: ignore
                thread_id=thread_id,
                run_id=run_id,
                assistant_id=assistant_id,
                arguments_dict=args,
            )
            return

        if name == "file_search":
            LOG.debug("TOOL-ROUTER ▸ route → _handle_file_search")
            self.handle_file_search(  # type: ignore
                thread_id=thread_id,
                run_id=run_id,
                assistant_id=assistant_id,
                arguments_dict=args,
            )
            return

        # ---- generic routing -------------------------------------------
        if name in PLATFORM_TOOLS:
            if name in SPECIAL_CASE_TOOL_HANDLING:
                LOG.debug("TOOL-ROUTER ▸ platform special-case → _process_tool_calls")
                self._process_tool_calls(  # type: ignore
                    thread_id,
                    assistant_id,
                    fc,
                    run_id,
                    api_key=api_key,
                )
            else:
                LOG.debug(
                    "TOOL-ROUTER ▸ platform native → _process_platform_tool_calls"
                )
                self._process_platform_tool_calls(  # type: ignore
                    thread_id,
                    assistant_id,
                    fc,
                    run_id,
                )
        else:
            LOG.debug("TOOL-ROUTER ▸ consumer tool → _process_tool_calls")
            self._process_tool_calls(  # type: ignore
                thread_id,
                assistant_id,
                fc,
                run_id,
                api_key=api_key,
            )
