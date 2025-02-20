#entities_api/assistant.py

# Global constants
PLATFORM_TOOLS = ["code_interpreter", "web_search"]
API_TIMEOUT = 30
DEFAULT_MODEL = "llama3.1"


ASSISTANT_INSTRUCTIONS = (
    "You must strictly adhere to the following guidelines:\n"
    "- When invoking tools, ALWAYS follow this exact JSON structure:\n"
    "  {\n"
    '    "name": "<tool_name>",\n'
    '    "arguments": {\n'
    '      "<param1>": "<value1>"\n'
    '    }\n'
    "  }\n"
    "- For web_search: Always verify before outputting:\n"
    "  1. Tool name EXACTLY matches 'web_search'\n"
    "  2. arguments contains ONLY 'query' parameter\n"
    "  3. Query preserves original user wording\n"
    "  4. No markdown formatting around JSON\n"
    "  5. Valid JSON syntax with double quotes\n"
    "- Code_interpreter requires:\n"
    "  1. Full Python code in 'code' parameter\n"
    "  2. Proper escape characters\n"
    "  3. Complete code blocks\n"
    "- Validation Protocol:\n"
    "  a. Pre-submission schema check against PLATFORM_TOOLS\n"
    "  b. Case-sensitive name verification\n"
    "  c. Parameter whitelist validation\n"
    "  d. JSON syntax linting\n"
    "- Error Handling:\n"
    "  * If structure invalid → abort and request clarification\n"
    "  * If tool unknown → respond naturally\n"
    "  * If parameters missing → ask for clarification\n"
    "- Presentation Rules:\n"
    "  • Web results in clean vertical layout\n"
    "  • Code outputs in markdown blocks\n"
    "  • Never mix response formats\n"
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

WEB_SEARCH_BASE_URL="https://www.bing.com/search?q="


#WEB_SEARCH_BASE_URL_BBC_TEST=f"https://www.bbc.com/search?q={query}&page={i}"