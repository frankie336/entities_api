#entities_api/assistant.py
# Global constants
PLATFORM_TOOLS = ["code_interpreter", "web_search", "search_vector_store"]

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
                        "max_results": {
                            "type": "integer",
                            "description": "The maximum number of results to return. Default is 5.",
                            "default": 5
                        }
                    },
                    "required": ["query"]
                }
            }
        },

{
    "type": "function",
    "function": {
        "name": "search_vector_store",
        "description": "Searches a vector store for the most relevant stored embeddings based on a query.",
        "parameters": {
            "type": "object",
            "properties": {

                "query": {
                    "type": "string",
                    "description": "The text query to search for in the vector store."
                },

            },
            "required": ["query"]
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
    "  1. **Extract Core Keywords:** Identify and focus on the main subjects and remove filler words.\n"
    "  2. **Exact Phrase Matching:** Enclose key phrases in double quotes (e.g., \"latest developments\").\n"
    "  3. **Boolean Operators:** Use operators like AND, OR, and the minus sign (`-`) to refine your query.\n"
    "  4. **Advanced Operators:** Utilize commands such as `site:`, `intitle:`, or `filetype:` to narrow results.\n"
    "  5. **Contextual Enrichment:** Expand the query with synonyms or clarify ambiguous terms to ensure precision.\n"
    "  6. **Iterative Refinement:** If initial results are unsatisfactory, adjust the query by adding/removing terms or incorporating date filters.\n"
    "\n"
    "- Always verify JSON structure before invoking web search:\n"
    "  {\n"
    '    "name": "web_search",\n'
    '    "arguments": {\n'
    '      "query": "<search term>"\n'
    '    }\n'
    "  }\n"
    "- **STRICT JSON FORMAT ENFORCEMENT:**\n"
    "  • Always use double quotes (`\"`) for JSON keys and values.\n"
    "  • Do **NOT** use single quotes (`'`), backticks, or non-standard formatting.\n"
    "  • Ensure the arguments object contains only expected parameters.\n"
    "  • If the JSON format is incorrect, **abort execution** and correct it before proceeding.\n"
    "\n"
    "🔹 **ERROR HANDLING:**\n"
    "- If a tool call structure is invalid → Abort and request clarification.\n"
    "- If a tool is unknown → Respond naturally without execution.\n"
    "- If parameters are missing → Ask the user for clarification.\n"
    "- If the JSON format is incorrect (e.g., uses single quotes, missing commas, or is malformed), **abort and correct before executing**.\n"
    "\n"
    "🔹 **ADDITIONAL VALIDATION RULE:**\n"
    "- Before executing any tool call, internally validate the JSON structure.\n"
    "- If any issue is detected (such as incorrect quoting, malformed JSON, or extra/missing parameters), fix it first before sending.\n"
    "\n"
    "Failure to comply will result in system rejection."
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

WEB_SEARCH_BASE_URL="https://www.bing.com/search"

#WEB_SEARCH_BASE_URL_BBC_TEST=f"https://www.bbc.com/search?q={query}&page={i}"