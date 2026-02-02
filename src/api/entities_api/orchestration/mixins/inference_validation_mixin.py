# src/api/entities_api/orchestration/mixins/inference_validation_mixin.py

import json
import re
from typing import Any, Dict, List, Union

from jsonschema import ValidationError, validate


class InferenceValidationMixin:
    """
    Responsible for validating the structural integrity and protocol compliance
    of LLM outputs before they are allowed to execute.

    Enforces:
    1. Decision Record existence (Intent).
    2. Intent-to-Action alignment (Anti-Drift).
    3. Tool Registry compliance (Anti-Hallucination).
    4. Argument Type Safety (Runtime Stability).
    """

    def validate_protocol_alignment(
        self,
        content_block: str,
        tool_call_obj: Any,
        assistant_tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Validates that the model's declared intent (Decision Record in content)
        matches its attempted action (Tool Call).

        Args:
            content_block: The text content from the message (should contain JSON).
            tool_call_obj: The tool call object from the provider.
            assistant_tools: The raw list of tools from assistant.tools.

        Returns:
            Dict with keys: 'valid' (bool), 'error' (str or None), 'telemetry' (dict).
        """

        # --- STAGE 1: Extract & Parse Decision Record ---
        decision = self._extract_decision_json(content_block)

        if not decision:
            return {
                "valid": False,
                "error": "PROTOCOL_VIOLATION: Missing or malformed Decision Record JSON.",
                "telemetry": None,
            }

        # Validate Decision Schema (Internal Telemetry Check)
        if "tool_name" not in decision:
            return {
                "valid": False,
                "error": "PROTOCOL_VIOLATION: Decision Record missing 'tool_name'.",
                "telemetry": decision,
            }

        # --- STAGE 2: Intent-Action Alignment ---
        intended_tool = decision.get("tool_name")
        actual_tool = tool_call_obj.function.name

        if intended_tool != actual_tool:
            return {
                "valid": False,
                "error": f"DRIFT_DETECTED: Intent '{intended_tool}' does not match Action '{actual_tool}'.",
                "telemetry": decision,
            }

        # --- STAGE 3: Registry & Schema Validation ---
        # We perform a JIT lookup against the allowed tools for this specific assistant
        validation_error = self._validate_against_registry(
            actual_tool, tool_call_obj.function.arguments, assistant_tools
        )

        if validation_error:
            return {"valid": False, "error": validation_error, "telemetry": decision}

        # --- PASS ---
        return {"valid": True, "error": None, "telemetry": decision}

    def _extract_decision_json(self, content: str) -> Union[Dict, None]:
        """
        Robustly attempts to extract JSON from the content block.
        Handles Markdown fences (```json ... ```) and raw text.
        """
        if not content:
            return None

        # 1. Try regex to find JSON block
        json_match = re.search(r"```json\s*(\{.*?\})\s*```", content, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # 2. If no fences, try finding the first '{' and last '}'
            # This is a fallback for models that forget markdown
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1:
                json_str = content[start : end + 1]
            else:
                return None

        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            return None

    def _validate_against_registry(
        self, tool_name: str, args_json_str: str, allowed_tools: List[Dict]
    ) -> Union[str, None]:
        """
        Checks if the tool exists in the list and if args match schema.
        Returns Error String if failed, None if passed.
        """
        target_tool_def = None

        # 1. Find the tool definition in the Assistant's specific config
        for tool in allowed_tools:
            # Case A: Custom Function
            if tool.get("type") == "function":
                if tool.get("function", {}).get("name") == tool_name:
                    target_tool_def = tool["function"]
                    break

            # Case B: Platform Tool (code_interpreter, file_search, etc)
            elif tool.get("type") == tool_name:
                # Platform tools are internal; we validate existence but usually trust the schema
                # because the provider (OpenAI/etc) handles the argument generation logic for these.
                return None

        if not target_tool_def:
            return f"HALLUCINATION_BLOCKED: Tool '{tool_name}' is not assigned to this Assistant."

        # 2. Validate Arguments against Schema (for Custom Functions)
        try:
            args = json.loads(args_json_str)
            if "parameters" in target_tool_def:
                validate(instance=args, schema=target_tool_def["parameters"])
        except json.JSONDecodeError:
            return "RUNTIME_ERROR: Tool arguments are not valid JSON."
        except ValidationError as e:
            return f"SCHEMA_VIOLATION: Arguments do not match definition. {e.message}"

        return None
