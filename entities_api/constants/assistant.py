# entities_api/assistant.py
# Global constants with enhanced validation
PLATFORM_TOOLS = ["code_interpreter", "web_search", "vector_store_search"]
API_TIMEOUT = 30
DEFAULT_MODEL = "llama3.1"

# Tool schemas with strict validation rules
BASE_TOOLS = [
    {
        "type": "code_interpreter",
        "function": {
            "name": "code_interpreter",
            "description": "Executes Python code in a sandbox environment and returns JSON output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute"},
                    "language": {"type": "string", "enum": ["python"]},
                    "user_id": {"type": "string", "description": "User identifier"}
                },
                "required": ["code", "language", "user_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "getAnnouncedPrefixes",
            "description": "Retrieves announced prefixes for an ASN",
            "parameters": {
                "type": "object",
                "properties": {
                    "resource": {"type": "string", "description": "ASN to query"},
                    "starttime": {"type": "string", "description": "Start time (ISO 8601)"},
                    "endtime": {"type": "string", "description": "End time (ISO 8601)"},
                    "min_peers_seeing": {
                        "type": "integer",
                        "description": "Minimum RIS peers seeing prefix",
                        "minimum": 1
                    }
                },
                "required": ["resource"]
            }
        }
    },
    {
        "type": "web_search",
        "function": {
            "name": "web_search",
            "description": "Performs web searches with structured results",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search terms using advanced operators",
                        "examples": [
                            "filetype:pdf cybersecurity report 2023",
                            "site:github.com AI framework"
                        ]
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "vector_store_search",
            "description": "Qdrant-compatible semantic search with advanced filters",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language search query"
                    },
                    "search_type": {
                        "type": "string",
                        "enum": [
                            "basic_semantic",
                            "filtered",
                            "complex_filters",
                            "temporal",
                            "explainable",
                            "hybrid"
                        ],
                        "description": "Search methodology"
                    },
                    "source_type": {
                        "type": "string",
                        "enum": ["chat", "documents", "memory"],
                        "description": "Data domain to search"
                    },
                    "filters": {
                        "type": "object",
                        "description": "Qdrant-compatible filter syntax",
                        "examples": {
                            "temporal": {"created_at": {"$gte": 1672531200, "$lte": 1704067200}},
                            "boolean": {"$or": [{"status": "active"}, {"priority": {"$gte": 7}}]}
                        }
                    },
                    "score_boosts": {
                        "type": "object",
                        "description": "Field-specific score multipliers",
                        "examples": {"priority": 1.5, "relevance": 2.0}
                    }
                },
                "required": ["query", "search_type", "source_type"]
            }
        }
    }
]

BASE_ASSISTANT_INSTRUCTIONS = (
    "🔹 **STRICT TOOL USAGE PROTOCOL**\n"
    "ALL tool calls MUST follow EXACT structure:\n"
    "{\n"
    '  "name": "<tool_name>",\n'
    '  "arguments": {\n'
    '    "<param>": "<value>"\n'
    '  }\n'
    "}\n\n"

    "🔹 **VECTOR SEARCH COMMANDMENTS**\n"
    "1. Temporal filters use UNIX timestamps (numeric)\n"
    "2. Numeric ranges: $eq/$neq/$gte/$lte\n"
    "3. Boolean logic: $or/$and/$not\n"
    "4. Text matching: $match/$contains\n\n"

    "🔹 **SEARCH TYPE EXAMPLES**\n"
    "1. Basic Semantic Search:\n"
    "{\n"
    '  "name": "vector_store_search",\n'
    '  "arguments": {\n'
    '    "query": "Ransomware attack patterns",\n'
    '    "search_type": "basic_semantic",\n'
    '    "source_type": "chat"\n'
    '  }\n'
    "}\n\n"

    "2. Temporal Search:\n"
    "{\n"
    '  "name": "vector_store_search",\n'
    '  "arguments": {\n'
    '    "query": "Zero-day vulnerabilities",\n'
    '    "search_type": "temporal",\n'
    '    "source_type": "chat",\n'
    '    "filters": {\n'
    '      "created_at": {\n'
    '        "$gte": 1672531200,\n'
    '        "$lte": 1704067200\n'
    '      }\n'
    '    }\n'
    '  }\n'
    "}\n\n"

    "3. Complex Filter Search:\n"
    "{\n"
    '  "name": "vector_store_search",\n'
    '  "arguments": {\n'
    '    "query": "Critical security patches",\n'
    '    "search_type": "complex_filters",\n'
    '    "source_type": "chat",\n'
    '    "filters": {\n'
    '      "$or": [\n'
    '        {"priority": {"$gt": 7}},\n'
    '        {"category": "emergency"}\n'
    '      ]\n'
    '    }\n'
    '  }\n'
    "}\n\n"

    "4. Assistant-Centric Search:\n"
    "{\n"
    '  "name": "vector_store_search",\n'
    '  "arguments": {\n'
    '    "query": "Quantum-resistant key exchange",\n'
    '    "search_type": "complex_filters",\n'
    '    "source_type": "chat",\n'
    '    "filters": {\n'
    '      "$and": [\n'
    '        {"message_role": "assistant"},\n'
    '        {"created_at": {"$gte": 1700000000}}\n'
    '      ]\n'
    '    }\n'
    '  }\n'
    "}\n\n"

    "5. Hybrid Source Search:\n"
    "{\n"
    '  "name": "vector_store_search",\n'
    '  "arguments": {\n'
    '    "query": "NIST PQC standardization",\n'
    '    "search_type": "temporal",\n'
    '    "source_type": "both",\n'
    '    "filters": {\n'
    '      "$or": [\n'
    '        {"doc_type": "technical_spec"},\n'
    '        {"thread_id": "thread_*"}\n'
    '      ]\n'
    '    }\n'
    '  }\n'
    "}\n\n"

    "🔹 **WEB SEARCH RULES**\n"
    "Optimized Query Example:\n"
    "{\n"
    '  "name": "web_search",\n'
    '  "arguments": {\n'
    '    "query": "CRYSTALS-Kyber site:nist.gov filetype:pdf"\n'
    '  }\n'
    "}\n\n"

    "🔹 **QUERY OPTIMIZATION PROTOCOL**\n"
    "1. Auto-condense queries to 5-7 key terms\n"
    "2. Default temporal filter: last 12 months\n"
    "3. Prioritize chat sources 2:1 over documents\n\n"

    "🔹 **RESULT CURATION RULES**\n"
    "1. Hide results with similarity scores <0.65\n"
    "2. Convert UNIX timestamps to human-readable dates\n"
    "3. Suppress raw JSON unless explicitly requested\n\n"

    "🔹 **VALIDATION IMPERATIVES**\n"
    "1. Double-quotes ONLY for strings\n"
    "2. No trailing commas\n"
    "3. UNIX timestamps as NUMBERS (no quotes)\n"
    "4. Operators must start with $\n\n"

    "🔹 **TERMINATION CONDITIONS**\n"
    "ABORT execution for:\n"
    "- Invalid timestamps (non-numeric/string)\n"
    "- Missing required params (query/search_type/source_type)\n"
    "- Unrecognized operators (e.g., gte instead of $gte)\n"
    "- Schema violations\n\n"

    "🔹 **ERROR HANDLING**\n"
    "- Invalid JSON → Abort and request correction\n"
    "- Unknown tool → Respond naturally\n"
    "- Missing parameters → Ask for clarification\n"
    "- Format errors → Fix before sending\n\n"

    "🔹 **OUTPUT FORMAT RULES**\n"
    "- NEVER use JSON backticks\n"
    "- ALWAYS use raw JSON syntax\n"
    "- Bold timestamps: **2025-03-01**\n"
    "- Example output:\n"
    '  {"name": "vector_store_search", "arguments": {\n'
    '    "query": "post-quantum migration",\n'
    '    "search_type": "basic_semantic",\n'
    '    "source_type": "chat"\n'
    '  }}\n\n'

    "Failure to comply will result in system rejection."
)


WEB_SEARCH_PRESENTATION_FOLLOW_UP_INSTRUCTIONS = (
    "Presentation Requirements:\n"
    "1. Mobile-first layout\n"
    "2. Domain authority badges\n"
    "3. Preserved source URLs\n"
    "4. Hidden metadata annotations\n"
    "Format Template:\n"
    "[Source](url)  \n"
    "![Favicon](favicon_url)  \n"
    "Excerpt...  \n"
    "---\n"
)

WEB_SEARCH_BASE_URL = "https://www.bing.co.uk/search"
JSON_VALIDATION_PATTERN = r'\{\s*"name"\s*:\s*".+?"\s*,\s*"arguments"\s*:\s*\{.*?\}\s*\}'


