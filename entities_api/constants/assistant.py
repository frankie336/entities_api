#entities_api/assistant.py
# Global constants
PLATFORM_TOOLS = ["code_interpreter", "web_search", "search_vector_store", "vector_store_search"]

API_TIMEOUT = 30
DEFAULT_MODEL = "llama3.1"

BASE_TOOLS = [
        {
            "type": "code_interpreter",
            "function": {
                "name": "code_interpreter",
                "description": "Executes a provided Python code snippet remotely in a sandbox environment and returns the raw output as a JSON object...",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "The Python code snippet to execute."},
                        "language": {"type": "string", "description": "The programming language.", "enum": ["python"]}
                    },
                    "required": ["code", "language", "user_id"]
                }
            }
        },

        {
            "type": "function",
            "function": {
                "name": "getAnnouncedPrefixes",
                "description": "Retrieves the announced prefixes for a given ASN",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "resource": {"type": "string", "description": "The ASN for which to retrieve the announced prefixes"},
                        "starttime": {"type": "string", "description": "The start time for the query"},
                        "endtime": {"type": "string", "description": "The end time for the query"},
                        "min_peers_seeing": {"type": "integer", "description": "Minimum RIS peers seeing the prefix"}
                    },
                    "required": ["resource"]
                }
            }
        },
        {
            "type": "web_search",
            "function": {
                "name": "web_search",
                "description": "Performs a web search based on a user-provided query and returns the results in a structured format.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query (e.g., 'latest trends in AI')."
                        },


                    },
                    "required": ["query"]
                }
            }
        },

{
    "type": "function",
    "function": {
        "name": "vector_store_search",
        "description": "Performs semantic search across various data sources with advanced capabilities",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language query for semantic search"
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
                    "description": """Type of search to perform:
- basic_semantic: Simple vector similarity search
- filtered: Metadata-filtered results
- complex_filters: Boolean logic filter combinations
- temporal: Time-weighted results
- explainable: Results with scoring explanations
- hybrid: Combined vector + keyword search"""
                },
                "source_type": {
                    "type": "string",
                    "enum": ["chat", "documents", "memory"],
                    "description": "Data domain to search"
                },
                "filters": {
                    "type": "object",
                    "description": "Metadata filters in Qdrant syntax"
                },
                "score_boosts": {
                    "type": "object",
                    "description": "Field-specific score multipliers"
                }
            },
            "required": ["query", "search_type", "source_type"]
        }
    }
}



    ]


BASE_ASSISTANT_INSTRUCTIONS = (
    "You must strictly adhere to the following guidelines:\n"
    "\n"
    "🔹 **GENERAL TOOL USAGE:**\n"
    "- When invoking tools, ALWAYS follow this exact JSON structure:\n"
    "  {\n"
    '    "name": "<tool_name>",\n'
    '    "arguments": {\n'
    '      "<param1>": "<value1>"\n'
    '    }\n'
    "  }\n"
    "- Validate all tool calls before execution:\n"
    "  1. Tool name must EXACTLY match the registered function.\n"
    "  2. Arguments must contain ONLY the expected parameters.\n"
    "  3. **JSON must be strictly valid:**\n"
    "     - Use double quotes (`\"`) for keys and string values.\n"
    "     - Do **NOT** use single quotes (`'`).\n"
    "     - Ensure proper comma placement—no trailing or missing commas.\n"
    "     - Keys must be lowercase and match the tool schema.\n"
    "\n"
    
    "🔹 **WEB SEARCH RULES & EFFECTIVE SEARCH GUIDELINES:**\n"
    "- Use `web_search` when:\n"
    "  • The user asks about current events or trending topics.\n"
    "  • The user seeks external knowledge beyond stored data.\n"
    "  • A vector store search yields no relevant results.\n"
    "\n"
    "• **Before executing a web search, follow these effective search guidelines:**\n"
    "\n"
    "**Examples of Searches"
    "Keep search terms terse. Do not copy convoluted questions from the user to make the search. Use terse terms like\n"
    "a human would. Search Engines will return relevant results as long as the core terms are included.\n"
    "Ensure that results are in English.\n"
    "About News:"
    "  {\n"
    '    "name": "web_search",\n'
    '    "arguments": {\n'
    '      "query": "Donald Trump+news site:.uk&setlang=en"\n'
    '    }\n'
    "  }\n"
    "About a Person:"
    "  {\n"
    '    "name": "web_search",\n'
    '    "arguments": {\n'
    '      "query": "Pearl Davis+move back to USA site:.uk&setlang=en"\n'
    '    }\n'
    "  }\n"
    "EXTRAPOLATE THE CORRECT SEARCH PATTERN FROM THE USERS INTENT. DO NOT USE THE USERS WORDS AS SEARCH PATTERNS SINCE"
    "THESE MAY NOT BE OPTIMAL FOR SEARCH ENGINES."
    "- Always verify JSON structure before invoking web search:\n"
    "  {\n"
    '    "name": "web_search",\n'
    '    "arguments": {\n'
    '      "query": "<search term>"\n'
    '    }\n'
    "  }\n"
    
    "\n\n🔹 **VECTOR SEARCH STRATEGIES:**\n"
    "Choose search types based on query context:\n"
    "1. Use 'basic_semantic' for general similarity searches\n"
    "2. Use 'filtered' when specific metadata criteria are known\n"
    "3. Use 'complex_filters' for boolean logic combinations\n"
    "4. Use 'temporal' for time-sensitive queries\n"
    "5. Use 'explainable' when justification is needed\n"
    "6. Use 'hybrid' for combined keyword/vector search\n\n"
    "Match source types to data domains:\n"
    "- 'chat': Conversation history\n"
    "- 'documents': Knowledge base/articles\n"
    "- 'memory': User-specific memories\n\n"
    "Example complex filter:\n"
    "{\n"
    '  "$or": [\n'
    '    {"priority": {"$gt": 7}},\n'
    '    {"category": "security"}\n'
    '  ],\n'
    '  "status": "active"\n'
    "}"
    
    "- **STRICT JSON FORMAT ENFORCEMENT:**\n"
    "  • Always use double quotes (`\"`) for JSON keys and values.\n"
    "  • Do **NOT** use single quotes (`'`), backticks, or non-standard formatting.\n"
    "  • Ensure the arguments object contains only expected parameters.\n"
    "  • If the JSON format is incorrect, **abort execution** and correct it before proceeding.\n"
    "\n"
    "🔹 **LATEX/MARKDOWN FORMATTING RULES:**\n"
    "- For mathematical expressions:\n"
    "  1. **Inline equations**: Wrap with single `$`\n"
    "     Example: `Einstein: $E = mc^2$` → Einstein: $E = mc^2$\n"
    "  2. **Display equations**: Wrap with double `$$`\n"
    "     Example:\n"
    "     $$F = ma$$\n"
    "\n"
    "- **Platform considerations**:\n"
    "  • On GitHub: Use `\\(...\\)` for inline and `\\[...\\]` for block equations.\n"
    "  • On MathJax-supported platforms: Use standard `$` and `$$` delimiters.\n"
    "\n"
    "- **Formatting requirements**:\n"
    "  1. Always include space between operators: `a + b` not `a+b`.\n"
    "  2. Use `\mathbf{}` for vectors/matrices: `$\mathbf{F} = m\mathbf{a}$`.\n"
    "  3. Avoid code blocks unless explicitly requested.\n"
    "  4. Provide rendering notes when context is unclear.\n"
    "\n"
    "🔹 **ERROR HANDLING:**\n"
    "- If a tool call structure is invalid → Abort and request clarification.\n"
    "- If a tool is unknown → Respond naturally without execution.\n"
    "- If parameters are missing → Ask the user for clarification.\n"
    "- If the JSON format is incorrect (e.g., uses single quotes, missing commas, or is malformed), **abort and correct before executing**.\n"
    "\n"
    "🔹 **ADDITIONAL VALIDATION RULE:**\n"
    "- Before executing any tool call, internally validate:\n"
    "  1. JSON structure integrity.\n"
    "  2. LaTeX delimiter consistency.\n"
    "  3. Platform-specific formatting requirements.\n"
    "- If any issue is detected (incorrect quoting, malformed JSON, or equation formatting errors), fix it first before sending.\n"
    "\n"
    "Failure to comply with ANY of these guidelines will result in system rejection."
)


WEB_SEARCH_PRESENTATION_FOLLOW_UP_INSTRUCTIONS = (
    "Presentation Requirements:\n"
    "1. Strictly NO code block formatting\n"
    "2. Use --- separators between items\n"
    "3. Embed favicons using markdown images\n"
    "4. Prioritize mobile-friendly layout\n"
    "5. Highlight domain authority\n"
    "6. Maintain source URL integrity\n"
    "7. Never modify search results content\n"
    "8. Mark metadata as hidden annotations\n"
    "Format Example:\n"
    "[Source Name](url)  \n"
    "![Favicon](favicon_url)  \n"
    "Relevant excerpt...  \n"
    "---\n"
    "Next result..."
)

WEB_SEARCH_BASE_URL="https://www.bing.co.uk/search"

#WEB_SEARCH_BASE_URL_BBC_TEST=f"https://www.bbc.com/search?q={query}&page={i}"