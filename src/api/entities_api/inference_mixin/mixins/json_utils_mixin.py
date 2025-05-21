"""
Regex-heavy helpers for:
• quote / comma sanitisation                       → ensure_valid_json
• generic schema guards                            → is_valid_function_call_response
• vector-store mongo-style query validator         → is_complex_vector_search
• multi-line / fence-stripped <fc>{…}</fc> search → extract_function_calls_within_body_of_text
• misc parsing helpers                             → extract_function_candidates, …
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Dict, List

from projectdavid_common.constants.ai_model_map import MODEL_MAP

from entities_api.services.logging_service import LoggingUtility

LOG = LoggingUtility()


class JsonUtilsMixin:

    @staticmethod
    def parse_code_interpreter_partial(text):
        """
        Parses a partial JSON-like string that begins with:
        {'name': 'code_interpreter', 'arguments': {'code':

        It captures everything following the 'code': marker.
        Note: Because the input is partial, the captured code may be incomplete.

        Returns:
            A dictionary with the key 'code' containing the extracted text,
            or None if no match is found.
        """
        pattern = re.compile(
            r"""
            \{\s*['"]name['"]\s*:\s*['"]code_interpreter['"]\s*,\s*   # "name": "code_interpreter"
            ['"]arguments['"]\s*:\s*\{\s*['"]code['"]\s*:\s*             # "arguments": {"code":
            (?P<code>.*)                                               # Capture the rest as code content
        """,
            re.VERBOSE | re.DOTALL,
        )

        match = pattern.search(text)
        if match:
            return {"code": match.group("code").strip()}
        else:
            return None

    # ------------------------------------------------------------------ #
    # House-keeping helpers                                              #
    # ------------------------------------------------------------------ #
    @staticmethod
    def convert_smart_quotes(text: str) -> str:
        return (
            text.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
        )

    # ------------------------------------------------------------------ #
    # Generic <fc> / tool-call validation                                #
    # ------------------------------------------------------------------ #
    @staticmethod
    def is_valid_function_call_response(obj: dict) -> bool:
        if not isinstance(obj, dict) or {"name", "arguments"} - obj.keys():
            return False
        if not isinstance(obj["name"], str) or not isinstance(obj["arguments"], dict):
            return False
        # no nested objects / lists in arguments
        return all(
            isinstance(k, str) and not isinstance(v, (list, dict))
            for k, v in obj["arguments"].items()
        )

    # ------------------------------------------------------------------ #
    # Simple recursive check for “$op” mongo-style vector queries        #
    # ------------------------------------------------------------------ #
    def is_complex_vector_search(self, data: dict) -> bool:
        for k, v in data.items():
            if k.startswith("$"):  # operator key
                if isinstance(v, dict) and not self.is_complex_vector_search(v):
                    return False
                if isinstance(v, list) and any(
                    isinstance(i, dict) and not self.is_complex_vector_search(i)
                    for i in v
                ):
                    return False
            else:  # normal key
                if isinstance(v, dict) and not self.is_complex_vector_search(v):
                    return False
                if isinstance(v, list):
                    return False
        return True

    # ------------------------------------------------------------------ #
    # Heavy-duty JSON fixer                                              #
    # ------------------------------------------------------------------ #
    def ensure_valid_json(self, text: str):  # noqa: C901 – complex but isolated
        if not isinstance(text, str) or not text.strip():
            return False

        txt = text.strip()
        # 1) try straight parse (also handles escaped JSON → str)
        try:
            parsed = json.loads(txt)
            if isinstance(parsed, dict):  # good!
                return parsed
            if isinstance(parsed, str):  # it was an escaped blob → try again
                txt = parsed
        except json.JSONDecodeError:
            pass

        # 2) heuristics – smart quotes and trailing commas
        txt = self.convert_smart_quotes(txt)
        txt = re.sub(r",(\s*[}\]])", r"\1", txt)  # kill dangling commas

        try:
            parsed = json.loads(txt)
            return parsed if isinstance(parsed, dict) else False
        except Exception as exc:
            LOG.debug("ensure_valid_json fell through: %s -- snippet=%s", exc, txt[:80])
            return False

    # ------------------------------------------------------------------ #
    # Regex helpers for locating embedded tool-calls                     #
    # ------------------------------------------------------------------ #
    _FENCE = re.compile(r"```(?:json)?(.*?)```", re.DOTALL)
    _GENERIC_CALL = re.compile(
        r"""\{.*?"name"\s*:\s*"(?P<name>[^"]+)".*?"arguments"\s*:\s*\{(?P<args>.*?)\}.*?\}""",
        re.DOTALL | re.VERBOSE,
    )

    def extract_function_calls_within_body_of_text(self, text: str) -> List[Dict]:
        text = self._FENCE.sub(r"\1", text)  # strip ```json fences
        text = self.convert_smart_quotes(text)
        matches = []
        for m in self._GENERIC_CALL.finditer(text):
            try:
                obj = json.loads(m.group(0))
                if self.is_valid_function_call_response(
                    obj
                ) or self.is_complex_vector_search(obj):
                    matches.append(obj)
            except Exception:
                continue
        return matches

    # super-loose candidate finder – rarely used but kept for feature parity
    _CANDIDATE = re.compile(
        r"""\{\s*(["'])name\1.*?["']arguments\1\s*:\s*\{.*?\}\s*\}""",
        re.DOTALL | re.VERBOSE,
    )

    def extract_function_candidates(self, text: str):
        return [m.group(0) for m in self._CANDIDATE.finditer(text)]

    # nested-object parser (unchanged, still used by a few legacy paths)
    _NESTED_RGX = re.compile(
        r"""\{\s*(?P<q1>["']).+?(?P=q1)\s*:\s*(?P<q2>["']).+?(?P=q2)\s*,\s*
            (?P<q3>["']).+?(?P=q3)\s*:\s*\{\s*(?P<q4>["']).+?(?P=q4)\s*:\s*
            (?P<q5>["']).+?(?P=q5).*?\}\s*\}""",
        re.DOTALL | re.VERBOSE,
    )

    def parse_nested_function_call_json(self, text: str):
        m = self._NESTED_RGX.search(text)
        if not m:
            return None
        groups = m.groupdict()
        return {
            "first_key": groups["q1"],
            "first_value": groups["q2"],
            "second_key": groups["q3"],
            "nested_key": groups["q4"],
            "nested_value": groups["q5"],
        }

    def _get_model_map(self, value: str) -> str | None:
        """
        Translate UI / front-end model aliases to the canonical name that
        Hyperbolic (or any other provider) expects.  Mirrors the helper that
        used to live in `BaseInference`.
        """
        return MODEL_MAP.get(value)
