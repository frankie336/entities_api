import json
import os

from dotenv import load_dotenv

from src.api.entities_api.platform_tools.definitions.code_interpreter import \
    code_interpreter
from src.api.entities_api.platform_tools.definitions.computer import computer
from src.api.entities_api.platform_tools.definitions.file_search import \
    file_search
from src.api.entities_api.platform_tools.definitions.web_search import \
    web_search

# ------------------------------------------------------------------
# 1. Concrete Tool Definitions (As provided in your prompt)
# ------------------------------------------------------------------

# ------------------------------------------------------------------
# 2. Input Tools Array (Mixed placeholders and concrete tools)
# ------------------------------------------------------------------

tools = [
    {"type": "code_interpreter"},
    {"type": "computer"},
    {"type": "file_search"},
    {
        "type": "function",
        "function": {
            "name": "get_flight_times",
            "description": "Get flight times",
            "parameters": {
                "type": "object",
                "properties": {
                    "departure": {"type": "string"},
                    "arrival": {"type": "string"},
                },
                "required": ["departure", "arrival"],
            },
        },
    },
]

print("--- BEFORE PROCESSING ---")
print(json.dumps(tools, indent=2))


# ------------------------------------------------------------------
# 3. The Logic to Replace Placeholders
# ------------------------------------------------------------------

# Map placeholder names to their concrete dictionary definitions
PLATFORM_TOOL_MAP = {
    "code_interpreter": code_interpreter,
    "computer": computer,
    "web_search": web_search,
    "file_search": file_search,
}

resolved_tools = []

for tool in tools:
    tool_type = tool.get("type")

    # Check if it is a placeholder:
    # 1. The type exists in our map
    # 2. It does NOT have a 'function' key (meaning it's not already defined)
    if tool_type in PLATFORM_TOOL_MAP and "function" not in tool:
        resolved_tools.append(PLATFORM_TOOL_MAP[tool_type])
    else:
        # Keep custom tools (like get_flight_times) or unknown types exactly as is
        resolved_tools.append(tool)

# Update the main variable
tools = resolved_tools

# ------------------------------------------------------------------
# 4. Result
# ------------------------------------------------------------------
print("\n--- AFTER PROCESSING ---")
print(json.dumps(tools, indent=2))
