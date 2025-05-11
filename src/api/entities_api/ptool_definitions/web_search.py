web_search = {
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
                },
            },
            "required": ["query"],
        },
    },
}
