# src/api/entities_api/orchestration/mixins/json_utils_mixin.py
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
from typing import Dict, Optional, Any

from projectdavid_common.constants.ai_model_map import MODEL_MAP

from src.api.entities_api.services.logging_service import LoggingUtility

LOG = LoggingUtility()


class JsonUtilsMixin:
    REASONING_PATTERN = re.compile("(<think>|</think>)")

    @staticmethod
    def parse_code_interpreter_partial(text: str) -> Optional[Dict[str, str]]:
        """
        Detects an in-progress code-interpreter tool call that looks like
            {"name": "code_interpreter", "arguments": {"code": ...
        and returns both the raw code fragment and a wrapped payload.
        """
        pattern = re.compile(
            r'\n\s*\{\s*["\']name["\']\s*:\s*["\']code_interpreter["\']\s*,\s*\n\s*["\']arguments["\']\s*:\s*\{\s*["\']code["\']\s*:\s*\n\s*(?P<code>.*)',
            re.VERBOSE | re.DOTALL,
        )
        m = pattern.search(text)
        if not m:
            return None
        code_fragment = m.group("code").strip()
        fc_json = {"name": "code_interpreter", "arguments": {"code": code_fragment}}
        fc_block = f"<fc>{json.dumps(fc_json, ensure_ascii=False)}</fc>"
        return {"code": code_fragment, "fc_block": fc_block}

    @staticmethod
    def convert_smart_quotes(text: str) -> str:
        return (
            text.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
        )

    @staticmethod
    def is_valid_function_call_response(json_data: dict) -> bool:
        """
        Generalized validation that works for any tool while enforcing protocol rules.
        CRITICAL UPDATE: Allows 'arguments' to be a dict OR a string (stringified JSON).
        Parsing of stringified arguments happens in ToolRoutingMixin._normalize_arguments.
        """
        try:
            if not isinstance(json_data, dict):
                return False

            # Check for unknown top-level keys
            if {"name", "arguments"} - json_data.keys():
                return False

            # Name must be a non-empty string
            if not isinstance(json_data["name"], str) or not json_data["name"].strip():
                return False

            # Arguments must be dict OR string (to be parsed later)
            args = json_data["arguments"]
            if not isinstance(args, (dict, str)):
                return False

            # If it is already a dict, ensure keys are strings
            if isinstance(args, dict):
                for key, value in args.items():
                    if not isinstance(key, str):
                        return False
                    # Note: We allow values to be list/dict (nested structures),
                    # unlike the previous restriction which blocked nested args.

            return True
        except (TypeError, KeyError):
            return False

    def is_complex_vector_search(self, data: dict) -> bool:
        """Recursively validate operators with $ prefix"""
        for key, value in data.items():
            if key.startswith("$"):
                if isinstance(value, dict) and (
                    not self.is_complex_vector_search(value)
                ):
                    return False
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict) and (
                            not self.is_complex_vector_search(item)
                        ):
                            return False
            elif isinstance(value, dict):
                if not self.is_complex_vector_search(value):
                    return False
            # Lists are allowed as values (e.g. $in: [1, 2]), return True here
            elif isinstance(value, list):
                pass
        return True

    def ensure_valid_json(self, text: str):
        """
        Ensures the input text represents a valid JSON dictionary.
        Handles:
        - Direct JSON parsing.
        - JSON strings that are escaped within an outer string.
        - Incorrect single quotes (`'`) -> double quotes (`"`).
        - Trailing commas before closing braces/brackets.
        """
        if not isinstance(text, str) or not text.strip():
            LOG.error("Received empty or non-string content for JSON validation.")
            return False

        original_text_for_logging = text[:200] + ("..." if len(text) > 200 else "")
        processed_text = text.strip()
        parsed_json = None

        # 1. Attempt Direct Parse
        try:
            intermediate_parse = json.loads(processed_text)
            if isinstance(intermediate_parse, dict):
                # LOG.debug("Direct JSON parse successful.")
                return intermediate_parse
            elif isinstance(intermediate_parse, str):
                LOG.warning("Initial parse resulted in string, attempting inner JSON parse.")
                processed_text = intermediate_parse
            else:
                return False
        except json.JSONDecodeError:
            pass  # Proceed to fixes
        except Exception as e:
            LOG.error(f"Unexpected error during initial JSON parse: {e}", exc_info=True)
            return False

        # 2. Heuristic Fixes
        fixed_text = processed_text
        try:
            # Fix Single Quotes if Double Quotes are absent
            if "'" in fixed_text and '"' not in fixed_text.replace("\\'", ""):
                # LOG.warning("Attempting single quote fix.")
                fixed_text = fixed_text.replace("'", '"')

            # Fix Trailing Commas: , } -> } and , ] -> ]
            fixed_text = re.sub(r",(\s*[}\]])", r"\1", fixed_text)

            parsed_json = json.loads(fixed_text)

            if isinstance(parsed_json, dict):
                return parsed_json
            else:
                return False

        except json.JSONDecodeError:
            # Silent failure expected on partial chunks
            return False
        except Exception as e:
            LOG.error(f"Error parsing fixed JSON: {e}", exc_info=True)
            return False

    _FENCE = re.compile("```(?:json)?(.*?)```", re.DOTALL)

    def extract_function_calls_within_body_of_text(self, text: str):
        """
        Extracts and validates tool invocation patterns from unstructured text.
        Primary use: Fallback for Legacy/Markdown formatted calls.
        """
        # Strip code fences
        text = re.sub("```(?:json)?(.*?)```", "\\1", text, flags=re.DOTALL)
        text = self.convert_smart_quotes(text)

        # Simple regex to find a JSON block that looks like a tool call.
        # This matches the structure: { ... "name": "...", ... "arguments": ... }
        # It handles newlines and spacing via DOTALL and VERBOSE.
        pattern = r"""
            \{                  # Opening brace
            .*?                 # Content
            "name"\s*:\s*"([^"]+)"  # Name key
            .*?                 # Content
            "arguments"\s*:\s*  # Arguments key
            (\{.*?\})           # Arguments object (greedy match to closing brace is tricky in regex)
            .*?                 # Remaining content
            \}                  # Closing brace
        """

        # NOTE: Regex extraction of nested JSON is inherently brittle.
        # This method is a heuristic fallback. The primary method in ToolRoutingMixin
        # uses find('{')/rfind('}') which is much more robust.

        tool_matches = []

        # We try to just parse the whole text as JSON first if it looks like one
        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            parsed = self.ensure_valid_json(stripped)
            if parsed and self.is_valid_function_call_response(parsed):
                tool_matches.append(parsed)
                return tool_matches

        return tool_matches

    def extract_function_candidates(self, text):
        """
        Extracts potential JSON function call patterns.
        """
        pattern = r"""
            \{                      # Opening curly brace
            \s*                     # Optional whitespace
            (["'])name\1\s*:\s*     # 'name' key with quotes
            (["'])(.*?)\2\s*,\s*    # Capture tool name
            (["'])arguments\4\s*:\s* # 'arguments' key
            (\{.*?\})               # Capture arguments object
            \s*\}                   # Closing curly brace
        """
        candidates = []
        try:
            matches = re.finditer(pattern, text, re.DOTALL | re.VERBOSE)
            for match in matches:
                candidate = match.group(0)
                if '"name"' in candidate and '"arguments"' in candidate:
                    candidates.append(candidate)
        except Exception:
            pass
        return candidates

    @staticmethod
    def parse_nested_function_call_json(text):
        """
        Parses a specific nested JSON structure.
        """
        pattern = re.compile(
            r"""
            \{\s*
            (?P<q1>["']) (?P<first_key> [^"']+?) (?P=q1) \s* : \s*
            (?P<q2>["']) (?P<first_value> [^"']+?) (?P=q2) \s* , \s*
            (?P<q3>["']) (?P<second_key> [^"']+?) (?P=q3) \s* : \s*
            \{\s*
            (?P<q4>["']) (?P<nested_key> [^"']+?) (?P=q4) \s* : \s*
            (?P<q5>["']) (?P<nested_value> .*?) (?P=q5) \s*
            } \s*
            } \s*
            """,
            re.VERBOSE | re.DOTALL,
        )
        match = pattern.search(text)
        if match:
            return {
                "first_key": match.group("first_key"),
                "first_value": match.group("first_value"),
                "second_key": match.group("second_key"),
                "nested_key": match.group("nested_key"),
                "nested_value": match.group("nested_value").strip(),
            }
        else:
            return None

    def _get_model_map(self, value: str) -> str | None:
        return MODEL_MAP.get(value)
