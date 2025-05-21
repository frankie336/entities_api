"""
High-level routing of <fc> tool-calls.

Responsibilities
----------------
• detect & validate <fc>{…}</fc> JSON blocks
• flip internal flags so only ONE handler runs
• dispatch to either platform-native or consumer handlers
"""

from __future__ import annotations

import json
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
        self._tool_response = value

    def get_tool_response_state(self) -> bool:
        return self._tool_response

    def set_function_call_state(self, value: Dict) -> None:
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
        Three-pass search:

        1. current streaming buffer (handles split <fc> blocks)
        2. finished assistant reply
        3. loose legacy JSON pattern
        """
        from .json_utils_mixin import \
            JsonUtilsMixin  # local import – avoid cycle

        if not isinstance(self, JsonUtilsMixin):  # type: ignore
            raise TypeError("ToolRoutingMixin must be mixed with JsonUtilsMixin")

        def _try_extract(txt: str) -> Optional[Dict]:
            m = self.FC_REGEX.search(txt)
            if not m:
                return None
            payload = m.group("payload")
            parsed = self.ensure_valid_json(payload)  # type: ignore[attr-defined]
            if parsed and (
                self.is_valid_function_call_response(parsed)  # type: ignore[attr-defined]
                or self.is_complex_vector_search(parsed)  # type: ignore[attr-defined]
            ):
                return parsed
            return None

        for source in (accumulated_content, assistant_reply):
            found = _try_extract(source)
            if found:
                self.set_tool_response_state(True)
                self.set_function_call_state(found)
                return found

        # legacy fall-back
        loose = self.extract_function_calls_within_body_of_text(assistant_reply)  # type: ignore[attr-defined]
        if loose:
            self.set_tool_response_state(True)
            self.set_function_call_state(loose[0])
            return loose[0]

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
            return  # nothing queued

        name = fc.get("name")
        args = fc.get("arguments", {})

        # ---- platform specials -----------------------------------------
        if name == "code_interpreter":
            yield from self.handle_code_interpreter_action(  # type: ignore
                thread_id=thread_id,
                run_id=run_id,
                assistant_id=assistant_id,
                arguments_dict=args,
            )
            return

        if name == "computer":
            yield from self.handle_shell_action(  # type: ignore
                thread_id=thread_id,
                run_id=run_id,
                assistant_id=assistant_id,
                arguments_dict=args,
            )
            return

        if name == "file_search":
            self._handle_file_search(  # type: ignore
                thread_id=thread_id,
                run_id=run_id,
                assistant_id=assistant_id,
                arguments_dict=args,
            )
            return

        # ---- generic routing -------------------------------------------
        if name in PLATFORM_TOOLS:
            if name in SPECIAL_CASE_TOOL_HANDLING:
                # treat as consumer
                self._process_tool_calls(  # type: ignore
                    thread_id,
                    assistant_id,
                    fc,
                    run_id,
                    api_key=api_key,
                )
            else:
                # normal platform route
                self._process_platform_tool_calls(  # type: ignore
                    thread_id,
                    assistant_id,
                    fc,
                    run_id,
                )
        else:
            # consumer tool
            self._process_tool_calls(  # type: ignore
                thread_id,
                assistant_id,
                fc,
                run_id,
                api_key=api_key,
            )
