update_scratchpad = {
    "type": "function",
    "function": {
        "name": "update_scratchpad",
        "description": (
            "Overwrites the entire scratchpad. Use this to restructure your plan, "
            "check off completed steps, or summarize your findings into a clean list."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The new full text content of the scratchpad.",
                }
            },
            "required": ["content"],
        },
    },
}
