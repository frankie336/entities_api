file_search = {
    "type": "function",
    "function": {
        "name": "file_search",
        "description": (
            "Runs a semantic (embedding‑based) and optionally filtered search over files. "
            "The vector store is selected automatically based on the assistant's configuration."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query_text": {
                    "type": "string",
                    "description": "Natural-language search query.",
                },
                "top_k": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 5,
                    "description": "Number of top passages to retrieve.",
                },
                "filters": {
                    "type": "object",
                    "description": (
                        "Optional payload filter (e.g., {'page': {'$lte': 5}})."
                    ),
                },
            },
            "required": ["query_text"],
        },
    },
}
