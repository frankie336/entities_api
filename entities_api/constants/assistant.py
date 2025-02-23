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
                "assistant_id": {
                    "type": "string",
                    "description": "The ID of the assistant performing the search."
                },
                "vector_store_id": {
                    "type": "string",
                    "description": "The ID of the vector store to search in."
                },
                "query": {
                    "type": "string",
                    "description": "The text query to search for in the vector store."
                },
                "top_k": {
                    "type": "integer",
                    "description": "The number of top results to return. Default is 5.",
                    "default": 5
                }
            },
            "required": ["assistant_id", "vector_store_id", "query"]
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
    "  1. Tool name must EXACTLY match registered function.\n"
    "  2. Arguments must contain ONLY expected parameters.\n"
    "  3. JSON must be valid with correct data types.\n"
    "\n"
    "🔹 **VECTOR STORE SEARCH RULES:**\n"
    "- ALWAYS use `search_vector_store` when:\n"
    "  • User asks about previously discussed topics.\n"
    "  • User references past interactions, files, or custom knowledge.\n"
    "  • User requests retrieval of specific stored content.\n"
    "- DO NOT use `search_vector_store` for real-time or web-based information.\n"
    "- Ensure the tool call follows this format:\n"
    "  {\n"
    '    "name": "search_vector_store",\n'
    '    "arguments": {\n'
    '      "query": "<user’s request>",\n'
    '      "top_k": 5\n'
    '    }\n'
    "  }\n"
    "- If search results are returned:\n"
    "  • Extract key insights and summarize.\n"
    "  • Present findings in a clear, structured format.\n"
    "  • If needed, synthesize multiple results into a coherent response.\n"
    "- If NO relevant results are found:\n"
    "  • Inform the user clearly: 'No stored knowledge found on this topic.'\n"
    "  • Ask if they want to rephrase the query.\n"
    "  • Offer to search the web instead.\n"
    "\n"
    "🔹 **WEB SEARCH RULES:**\n"
    "- Use `web_search` when:\n"
    "  • User asks about current events or trending topics.\n"
    "  • User seeks external knowledge beyond stored data.\n"
    "  • Vector store search yields no relevant results.\n"
    "- Always verify JSON structure before invoking:\n"
    "  {\n"
    '    "name": "web_search",\n'
    '    "arguments": {\n'
    '      "query": "<search term>",\n'
    '      "max_results": 5\n'
    '    }\n'
    "  }\n"
    "\n"
    "🔹 **CODE INTERPRETER RULES:**\n"
    "- Only use `code_interpreter` for tasks involving:\n"
    "  • Data analysis, calculations, and simulations.\n"
    "  • Generating plots or structured outputs.\n"
    "- Ensure code integrity:\n"
    "  1. Full Python code block inside 'code' parameter.\n"
    "  2. Proper escape characters where needed.\n"
    "  3. No partial or incomplete snippets.\n"
    "\n"
    "🔹 **ERROR HANDLING:**\n"
    "- If tool call structure is invalid → Abort and request clarification.\n"
    "- If tool is unknown → Respond naturally without execution.\n"
    "- If parameters are missing → Ask user for clarification.\n"
    "\n"
    "🔹 **PRESENTATION RULES:**\n"
    "- Web search results must be formatted in a clean, vertical layout.\n"
    "- Code outputs must be wrapped in proper markdown blocks.\n"
    "- Vector store results should be structured, summarized, and contextualized.\n"
    "- NEVER mix response formats (e.g., avoid interleaving raw JSON and text).\n"
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

WEB_SEARCH_BASE_URL="https://www.bing.co.uk/search"
#WEB_SEARCH_BASE_URL_BBC_TEST=f"https://www.bbc.com/search?q={query}&page={i}"