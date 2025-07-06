BASE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "code_interpreter",
            "description": "Executes Python code in a sandbox environment and returns JSON output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute"}
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_search",
            "description": "Runs a semantic (embedding‑based) + keyword filter search over files that have been embedded into one or more vector stores. Results are returned as an array of metadata objects with relevance scores.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural‑language search text.",
                    },
                    "vector_store_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": 'Vector‑store IDs to search. Omit to use the assistant‑level binding supplied in tools=[{"type": "file_search", "vector_store_ids": [...] }].',
                    },
                    "top_k": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "default": 5,
                        "description": "Maximum hits to return per store.",
                    },
                    "filters": {
                        "type": "object",
                        "description": "Optional Qdrant payload‑filter object, identical in structure to the `filters` argument of search_vector_store().",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Performs web searches with structured results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search terms using advanced operators.",
                        "examples": [
                            "filetype:pdf cybersecurity report 2023",
                            "site:github.com AI framework",
                        ],
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "computer",
            "description": "Simulates a personal Linux workstation with internet access. Executes a list of terminal commands in a recoverable session, streaming output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "commands": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Sequential Linux commands as if typed directly into the terminal.",
                    }
                },
                "required": ["commands"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vector_store_search",
            "description": "Qdrant‑compatible semantic search with advanced filters.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural‑language search query.",
                    },
                    "search_type": {
                        "type": "string",
                        "enum": [
                            "basic_semantic",
                            "filtered",
                            "complex_filters",
                            "temporal",
                            "explainable",
                            "hybrid",
                        ],
                        "description": "Search methodology.",
                    },
                    "source_type": {
                        "type": "string",
                        "enum": ["chat", "documents", "memory"],
                        "description": "Data domain to search.",
                    },
                    "filters": {
                        "type": "object",
                        "description": "Qdrant‑compatible filter syntax.",
                        "examples": {
                            "temporal": {
                                "created_at": {"$gte": 1672531200, "$lte": 1704067200}
                            },
                            "boolean": {
                                "$or": [{"status": "active"}, {"priority": {"$gte": 7}}]
                            },
                        },
                    },
                    "score_boosts": {
                        "type": "object",
                        "description": "Field‑specific score multipliers.",
                        "examples": {"priority": 1.5, "relevance": 2.0},
                    },
                },
                "required": ["query", "search_type", "source_type"],
            },
        },
    },
]
