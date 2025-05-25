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
    def is_valid_function_call_response(json_data: dict) -> bool:
        """
        Generalized validation that works for any tool while enforcing protocol rules.
        Doesn't validate specific parameter values, just ensures proper structure.
        """
        try:
            # Base structure check
            if not isinstance(json_data, dict):
                return False

            # Required top-level keys
            if {"name", "arguments"} - json_data.keys():
                return False

            # Name validation
            if not isinstance(json_data["name"], str) or not json_data["name"].strip():
                return False

            # Arguments validation
            if not isinstance(json_data["arguments"], dict):
                return False

            # Value type preservation check
            for key, value in json_data["arguments"].items():
                if not isinstance(key, str):
                    return False
                if isinstance(value, (list, dict)):
                    return False  # Prevent nested structures per guidelines

            return True

        except (TypeError, KeyError):
            return False

    # ------------------------------------------------------------------ #
    # Simple recursive check for “$op” mongo-style vector queries        #
    # ------------------------------------------------------------------ #
    def is_complex_vector_search(self, data: dict) -> bool:
        """Recursively validate operators with $ prefix"""
        for key, value in data.items():
            if key.startswith("$"):
                # Operator values can be primitives or nested structures
                if isinstance(value, dict) and not self.is_complex_vector_search(value):
                    return False
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict) and not self.is_complex_vector_search(
                            item
                        ):
                            return False
            else:
                # Non-operator keys can have any value EXCEPT unvalidated dicts
                if isinstance(value, dict):
                    if not self.is_complex_vector_search(
                        value
                    ):  # Recurse into nested dicts
                        return False
                elif isinstance(value, list):
                    return False  # Maintain original list prohibition

        return True

    # ------------------------------------------------------------------ #
    # Heavy-duty JSON fixer                                              #
    # ------------------------------------------------------------------ #
    def ensure_valid_json(self, text: str):
        """
        Ensures the input text represents a valid JSON dictionary.
        Handles:
        - Direct JSON parsing.
        - JSON strings that are escaped within an outer string (e.g., '"{\"key\": \"value\"}"').
        - Incorrect single quotes (`'`) -> double quotes (`"`).
        - Trailing commas before closing braces/brackets.

        Returns a parsed JSON dictionary if successful, otherwise returns False.
        """
        global fixed_text
        if not isinstance(text, str) or not text.strip():
            LOG.error("Received empty or non-string content for JSON validation.")
            return False

        original_text_for_logging = text[:200] + (
            "..." if len(text) > 200 else ""
        )  # Log snippet
        processed_text = text.strip()
        parsed_json = None

        # --- Stage 1: Attempt Direct or Unescaping Parse ---
        try:
            # Attempt parsing directly. This might succeed if the input is already valid JSON,
            # OR if it's an escaped JSON string like "\"{\\\"key\\\": \\\"value\\\"}\"".
            # In the latter case, json.loads() will return the *inner* string "{\"key\": \"value\"}".
            intermediate_parse = json.loads(processed_text)

            if isinstance(intermediate_parse, dict):
                # Direct parse successful and it's a dictionary!
                LOG.debug("Direct JSON parse successful.")
                parsed_json = intermediate_parse
                # We can return early if we don't suspect trailing commas in this clean case
                # Let's apply comma fix just in case, doesn't hurt.
                # Fall through to Stage 2 for potential comma fixing.

            elif isinstance(intermediate_parse, str):
                # Parsed successfully, but resulted in a string.
                # This means the original 'processed_text' was an escaped JSON string.
                # 'intermediate_parse' now holds the actual JSON string we need to parse.
                LOG.warning(
                    "Initial parse resulted in string, attempting inner JSON parse."
                )
                processed_text = (
                    intermediate_parse  # Use the unescaped string for the next stage
                )
                # Fall through to Stage 2 for parsing and fixes

            else:
                # Parsed to something other than dict or string (e.g., list, number)
                LOG.error(
                    f"Direct JSON parse resulted in unexpected type: {type(intermediate_parse)}. Expected dict or escaped string."
                )
                return False  # Not suitable for function call structure

        except json.JSONDecodeError:
            # Direct parse failed. This is expected if it needs quote/comma fixes,
            # or if it wasn't an escaped string to begin with.
            LOG.debug("Direct/Unescaping parse failed. Proceeding to fixes.")
            # Fall through to Stage 2 where 'processed_text' is still the original stripped text.
            pass  # Continue to Stage 2
        except Exception as e:
            # Catch unexpected errors during the first parse attempt
            LOG.error(
                f"Unexpected error during initial JSON parse stage: {e}. Text: {original_text_for_logging}",
                exc_info=True,
            )
            return False

        # --- Stage 2: Apply Fixes and Attempt Final Parse ---
        # This stage runs if:
        # 1. Direct parse succeeded yielding a dict (parsed_json is set) -> mainly for comma fix.
        # 2. Direct parse yielded a string (processed_text updated) -> needs parsing + fixes.
        # 3. Direct parse failed (processed_text is original) -> needs parsing + fixes.

        if parsed_json and isinstance(parsed_json, dict):
            # If already parsed to dict, just check for/fix trailing commas in string representation
            # This is less common, usually fix before parsing. Let's skip for simplicity unless needed.
            LOG.debug(
                "JSON already parsed, skipping fix stage (commas assumed handled or valid)."
            )
            # If trailing commas *after* initial parse are a problem, convert dict back to string, fix, re-parse (complex).
            # Let's assume the initial parse handled it or it was valid.
            pass  # proceed to return parsed_json
        else:
            # We need to parse 'processed_text' (either original or unescaped string) after fixes
            try:
                # Fix 1: Standardize Single Quotes (Use cautiously)
                # Only apply if single quotes are present and double quotes are likely not intentional structure
                # This is heuristic and might break valid JSON with single quotes in string values.
                if "'" in processed_text and '"' not in processed_text.replace(
                    "\\'", ""
                ):  # Avoid replacing escaped quotes if possible
                    LOG.warning(
                        f"Attempting single quote fix on: {processed_text[:100]}..."
                    )
                    fixed_text = processed_text.replace("'", '"')
                else:
                    fixed_text = processed_text  # No quote fix needed or too risky

                # Fix 2: Remove Trailing Commas (before closing brace/bracket)
                # Handles cases like [1, 2,], {"a":1, "b":2,}
                fixed_text = re.sub(r",(\s*[}\]])", r"\1", fixed_text)

                # Final Parse Attempt
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

        # --- Stage 3: Final Check and Return ---
        if isinstance(parsed_json, dict):
            return parsed_json
        else:
            # Should technically be caught earlier, but as a safeguard
            LOG.error("Final check failed: parsed_json is not a dictionary.")
            return False

    # ------------------------------------------------------------------ #
    # Regex helpers for locating embedded tool-calls                     #
    # ------------------------------------------------------------------ #
    _FENCE = re.compile(r"```(?:json)?(.*?)```", re.DOTALL)
    _GENERIC_CALL = re.compile(
        r"""\{.*?"name"\s*:\s*"(?P<name>[^"]+)".*?"arguments"\s*:\s*\{(?P<args>.*?)\}.*?\}""",
        re.DOTALL | re.VERBOSE,
    )

    def extract_function_calls_within_body_of_text(self, text: str):
        """
        Extracts and validates all tool invocation patterns from unstructured text.
        Handles multi-line JSON and schema validation without recursive patterns.
        """
        # Remove markdown code fences (e.g., ```json ... ```)
        text = re.sub(r"```(?:json)?(.*?)```", r"\1", text, flags=re.DOTALL)

        # Normalization phase
        text = re.sub(r"[“”]", '"', text)
        text = re.sub(r"(\s|\\n)+", " ", text)

        # Simplified pattern without recursion
        pattern = r"""
            \{         # Opening curly brace
            .*?        # Any characters
            "name"\s*:\s*"(?P<name>[^"]+)"
            .*?        # Any characters
            "arguments"\s*:\s*\{(?P<args>.*?)\}
            .*?        # Any characters
            \}         # Closing curly brace
        """

        tool_matches = []
        for match in re.finditer(pattern, text, re.DOTALL | re.VERBOSE):
            try:
                # Reconstruct with proper JSON formatting
                raw_json = match.group()
                parsed = json.loads(raw_json)

                # Schema validation
                if not all(key in parsed for key in ["name", "arguments"]):
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
        # Regex pattern explanation:
        # - Looks for {...} structures with 'name' and 'arguments' keys
        # - Allows for nested JSON structures
        # - Tolerates some invalid JSON formatting that might appear in streams
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
                # Validate basic structure before adding
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
            r"""
            \{\s*                                                      # Opening brace of outer object
            (?P<q1>["']) (?P<first_key> [^"']+?) (?P=q1) \s* : \s*      # First key
            (?P<q2>["']) (?P<first_value> [^"']+?) (?P=q2) \s* , \s*    # First value
            (?P<q3>["']) (?P<second_key> [^"']+?) (?P=q3) \s* : \s*     # Second key
            \{\s*                                                      # Opening brace of nested object
            (?P<q4>["']) (?P<nested_key> [^"']+?) (?P=q4) \s* : \s*     # Nested key
            (?P<q5>["']) (?P<nested_value> .*?) (?P=q5) \s*             # Nested value (multiline allowed)
            } \s*                                                     # Closing brace of nested object
            } \s*                                                     # Closing brace of outer object
        """,
            re.VERBOSE | re.DOTALL,
        )  # re.DOTALL allows matching multiline values

        match = pattern.search(text)
        if match:
            return {
                "first_key": match.group("first_key"),
                "first_value": match.group("first_value"),
                "second_key": match.group("second_key"),
                "nested_key": match.group("nested_key"),
                "nested_value": match.group(
                    "nested_value"
                ).strip(),  # Remove trailing whitespace
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
