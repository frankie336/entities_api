# src/api/entities_api/platform_tools/definitions/record_tool_decision.py
record_tool_decision = {
    "name": "record_tool_decision",
    "description": "Record the structured decision basis for selecting a tool before calling it.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": ["selected_tool", "selection_basis", "confidence"],
        "properties": {
            "selected_tool": {
                "type": "string",
                "description": "Name of the tool that will be called next.",
            },
            "selection_basis": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "requires_external_data",
                        "requires_retrieval",
                        "requires_computation",
                        "requires_code_execution",
                        "requires_file_access",
                        "user_explicit_request",
                        "structured_output_required",
                        "multi_step_task",
                        "freshness_required",
                    ],
                },
                "minItems": 1,
                "maxItems": 4,
            },
            "input_signals": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "contains_question",
                        "contains_numbers",
                        "contains_file_reference",
                        "contains_url",
                        "contains_code",
                        "mentions_document",
                        "ambiguous_request",
                        "calculation_detected",
                    ],
                },
                "minItems": 0,
                "maxItems": 6,
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "alternatives_considered": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 3,
            },
        },
    },
}
