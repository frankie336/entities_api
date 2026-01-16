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

from projectdavid_common.constants.ai_model_map import MODEL_MAP

from src.api.entities_api.services.logging_service import LoggingUtility

LOG = LoggingUtility()


class JsonUtilsMixin:
    REASONING_PATTERN = re.compile("(<think>|</think>)")
    import json
    import re
    from typing import Dict, Optional

    @staticmethod
    def parse_code_interpreter_partial(text: str) -> Optional[Dict[str, str]]:
        """
        Detects an in-progress code-interpreter tool call that looks like

            {"name": "code_interpreter", "arguments": {"code": ...

        and returns **both** the raw code fragment and a fully wrapped
        <fc> ... </fc> payload that can be appended to the function-call
        buffer.

        Returns
        -------
        dict | None
            {
                "code":     "<python …  (may be incomplete)",
                "fc_block": "<fc>{"name": "code_interpreter", ...}</fc>"
            }
            or *None* if the pattern is not found.
        """
        pattern = re.compile(
            '\n            \\{\\s*["\']name["\']\\s*:\\s*["\']code_interpreter["\']\\s*,\\s*\n            ["\']arguments["\']\\s*:\\s*\\{\\s*["\']code["\']\\s*:\\s*\n            (?P<code>.*)                        # capture the tail after "code":\n            ',
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
        Doesn't validate specific parameter values, just ensures proper structure.
        """
        try:
            if not isinstance(json_data, dict):
                return False
            if {"name", "arguments"} - json_data.keys():
                return False
            if not isinstance(json_data["name"], str) or not json_data["name"].strip():
                return False
            if not isinstance(json_data["arguments"], dict):
                return False
            for key, value in json_data["arguments"].items():
                if not isinstance(key, str):
                    return False
                if isinstance(value, (list, dict)):
                    return False
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
            elif isinstance(value, list):
                return False
        return True

    def ensure_valid_json(self, text: str):
        """
        Ensures the input text represents a valid JSON dictionary.
        Handles:
        - Direct JSON parsing.
        - JSON strings that are escaped within an outer string (e.g., '"{"key": "value"}"').
        - Incorrect single quotes (`'`) -> double quotes (`"`).
        - Trailing commas before closing braces/brackets.

        Returns a parsed JSON dictionary if successful, otherwise returns False.
        """
        global fixed_text
        if not isinstance(text, str) or not text.strip():
            LOG.error("Received empty or non-string content for JSON validation.")
            return False
        original_text_for_logging = text[:200] + ("..." if len(text) > 200 else "")
        processed_text = text.strip()
        parsed_json = None
        try:
            intermediate_parse = json.loads(processed_text)
            if isinstance(intermediate_parse, dict):
                LOG.debug("Direct JSON parse successful.")
                parsed_json = intermediate_parse
            elif isinstance(intermediate_parse, str):
                LOG.warning(
                    "Initial parse resulted in string, attempting inner JSON parse."
                )
                processed_text = intermediate_parse
            else:
                LOG.error(
                    f"Direct JSON parse resulted in unexpected type: {type(intermediate_parse)}. Expected dict or escaped string."
                )
                return False
        except json.JSONDecodeError:
            LOG.debug("Direct/Unescaping parse failed. Proceeding to fixes.")
            pass
        except Exception as e:
            LOG.error(
                f"Unexpected error during initial JSON parse stage: {e}. Text: {original_text_for_logging}",
                exc_info=True,
            )
            return False
        if parsed_json and isinstance(parsed_json, dict):
            LOG.debug(
                "JSON already parsed, skipping fix stage (commas assumed handled or valid)."
            )
            pass
        else:
            try:
                if "'" in processed_text and '"' not in processed_text.replace(
                    "\\'", ""
                ):
                    LOG.warning(
                        f"Attempting single quote fix on: {processed_text[:100]}..."
                    )
                    fixed_text = processed_text.replace("'", '"')
                else:
                    fixed_text = processed_text
                fixed_text = re.sub(",(\\s*[}\\]])", "\\1", fixed_text)
                parsed_json = json.loads(fixed_text)
                if not isinstance(parsed_json, dict):
                    LOG.error(
                        f"Parsed JSON after fixes is not a dictionary (type: {type(parsed_json)}). Text after fixes: {fixed_text[:200]}..."
                    )
                    return False
                LOG.info("JSON successfully parsed after fixes.")
            except json.JSONDecodeError as e:
                LOG.error(
                    f"Failed to parse JSON even after fixes. Error: {e}. Text after fixes attempt: {fixed_text[:200]}..."
                )
                return False
            except Exception as e:
                LOG.error(
                    f"Unexpected error during JSON fixing/parsing stage: {e}. Text: {original_text_for_logging}",
                    exc_info=True,
                )
                return False
        if isinstance(parsed_json, dict):
            return parsed_json
        else:
            LOG.error("Final check failed: parsed_json is not a dictionary.")
            return False

    _FENCE = re.compile("```(?:json)?(.*?)```", re.DOTALL)
    _GENERIC_CALL = re.compile(
        '\\{.*?"name"\\s*:\\s*"(?P<name>[^"]+)".*?"arguments"\\s*:\\s*\\{(?P<args>.*?)\\}.*?\\}',
        re.DOTALL | re.VERBOSE,
    )

    def extract_function_calls_within_body_of_text(self, text: str):
        """
        Extracts and validates all tool invocation patterns from unstructured text.
        Handles multi-line JSON and schema validation without recursive patterns.
        """
        text = re.sub("```(?:json)?(.*?)```", "\\1", text, flags=re.DOTALL)
        text = re.sub("[“”]", '"', text)
        text = re.sub("(\\s|\\\\n)+", " ", text)
        pattern = '\n            \\{         # Opening curly brace\n            .*?        # Any characters\n            "name"\\s*:\\s*"(?P<name>[^"]+)"\n            .*?        # Any characters\n            "arguments"\\s*:\\s*\\{(?P<args>.*?)\\}\n            .*?        # Any characters\n            \\}         # Closing curly brace\n        '
        tool_matches = []
        for match in re.finditer(pattern, text, re.DOTALL | re.VERBOSE):
            try:
                raw_json = match.group()
                parsed = json.loads(raw_json)
                if not all((key in parsed for key in ["name", "arguments"])):
                    continue
                if not isinstance(parsed["arguments"], dict):
                    continue
                tool_matches.append(parsed)
            except (json.JSONDecodeError, KeyError):
                continue
        return tool_matches

    def extract_function_candidates(self, text):
        """
        Extracts potential JSON function call patterns from arbitrary text positions.
        Handles cases where function calls are embedded within other content.
        """
        pattern = "\n            \\{                      # Opening curly brace\n            \\s*                     # Optional whitespace\n            ([\"'])name\\1\\s*:\\s*     # 'name' key with quotes\n            ([\"'])(.*?)\\2\\s*,\\s*    # Capture tool name\n            ([\"'])arguments\\4\\s*:\\s* # 'arguments' key\n            (\\{.*?\\})               # Capture arguments object\n            \\s*\\}                   # Closing curly brace\n        "
        candidates = []
        try:
            matches = re.finditer(pattern, text, re.DOTALL | re.VERBOSE)
            for match in matches:
                candidate = match.group(0)
                if '"name"' in candidate and '"arguments"' in candidate:
                    candidates.append(candidate)
        except Exception as e:
            LOG.error(f"Candidate extraction error: {str(e)}")
        return candidates

    @staticmethod
    def parse_nested_function_call_json(text):
        """
        Parses a JSON-like string with a nested object structure and variable keys,
        supporting both single and double quotes, as well as multiline values.

        Expected pattern:
        {
            <quote>first_key<quote> : <quote>first_value<quote>,
            <quote>second_key<quote> : {
                <quote>nested_key<quote> : <quote>nested_value<quote>
            }
        }

        The regex uses named groups for the opening quote of each field and backreferences
        them to ensure the same type of quote is used to close the string.

        Returns a dictionary with the following keys if matched:
          - 'first_key'
          - 'first_value'
          - 'second_key'
          - 'nested_key'
          - 'nested_value'

        If no match is found, returns None.
        """
        pattern = re.compile(
            "\n            \\{\\s*                                                      # Opening brace of outer object\n            (?P<q1>[\"']) (?P<first_key> [^\"']+?) (?P=q1) \\s* : \\s*      # First key\n            (?P<q2>[\"']) (?P<first_value> [^\"']+?) (?P=q2) \\s* , \\s*    # First value\n            (?P<q3>[\"']) (?P<second_key> [^\"']+?) (?P=q3) \\s* : \\s*     # Second key\n            \\{\\s*                                                      # Opening brace of nested object\n            (?P<q4>[\"']) (?P<nested_key> [^\"']+?) (?P=q4) \\s* : \\s*     # Nested key\n            (?P<q5>[\"']) (?P<nested_value> .*?) (?P=q5) \\s*             # Nested value (multiline allowed)\n            } \\s*                                                     # Closing brace of nested object\n            } \\s*                                                     # Closing brace of outer object\n        ",
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
        """
        Translate UI / front-end model aliases to the canonical name that
        Hyperbolic (or any other provider) expects.  Mirrors the helper that
        used to live in `BaseInference`.
        """
        return MODEL_MAP.get(value)
