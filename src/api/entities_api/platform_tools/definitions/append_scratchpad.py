append_scratchpad = (
    {
        "type": "function",
        "function": {
            "name": "append_scratchpad",
            "description": (
                "Appends a specific note to the bottom of the scratchpad. "
                "Use this to quickly save a fact, URL, or number without rewriting the whole plan."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "note": {
                        "type": "string",
                        "description": "The text to append (e.g., 'Found revenue: $50M').",
                    }
                },
                "required": ["note"],
            },
        },
    },
)
