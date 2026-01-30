import json
from typing import Any, Dict, List, Optional

from src.api.entities_api.constants.tools import PLATFORM_TOOL_MAP


def resolve_and_prioritize_platform_tools(
    tools: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """
    Resolves placeholder tool definitions into concrete platform tools
    and reorders them so Platform tools appear before User tools.

    Robustness:
    - Handles None or empty lists safely.
    - If no placeholders are found, returns the original array structure.
    - Preserves user tool order relative to other user tools.
    """

    # 1. Safety Check: Handle None or empty input
    if not tools:
        return []

    resolved_platform_tools = []
    resolved_user_tools = []

    # 2. Iterate through the inbound tools array
    for tool in tools:
        # Skip invalid entries if the list contains non-dicts
        if not isinstance(tool, dict):
            continue

        tool_type = tool.get("type")

        # Check if it is a placeholder for a platform tool:
        # 1. It exists in our map
        # 2. It isn't explicitly defined as a "function" (user tool)
        # 3. It doesn't have a "function" key (already resolved/defined)
        if (
            tool_type in PLATFORM_TOOL_MAP
            and tool_type != "function"
            and "function" not in tool
        ):
            # It is a placeholder -> Resolve it and bucket as Platform
            resolved_platform_tools.append(PLATFORM_TOOL_MAP[tool_type])
        else:
            # It is a user tool, a custom tool, or a regular function
            # -> Bucket as User (Preserves original object)
            resolved_user_tools.append(tool)

    # 3. MERGE: Platform Tools FIRST, User Tools LAST
    return resolved_platform_tools + resolved_user_tools


# ------------------------------------------------------------------
# TEST: Scenario with NO placeholders (User tools only)
# ------------------------------------------------------------------
if __name__ == "__main__":

    # Input with NO platform placeholders
    user_only_tools = [
        {
            "type": "function",
            "function": {
                "name": "get_flight_times",
                "description": "User defined tool",
                "parameters": {},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "send_email",
                "parameters": {},
            },
        },
    ]

    print("--- Processing User-Only Array ---")
    result = resolve_and_prioritize_tools(user_only_tools)
    print(json.dumps(result, indent=2))

    # Verify it is exactly the same length and content
    assert len(result) == 2
    assert result[0]["function"]["name"] == "get_flight_times"
    print("\n[Success] Function handled array without placeholders correctly.")

# ------------------------------------------------------------------
# USAGE EXAMPLE
# ------------------------------------------------------------------
if __name__ == "__main__":
    # INPUT: Mixed Tools (Platform tools buried in the middle)
    incoming_tools = [
        {
            "type": "function",
            "function": {
                "name": "get_flight_times",
                "description": "User defined tool",
                "parameters": {},
            },
        },
        {"type": "code_interpreter"},  # Platform placeholder
        {"type": "computer"},  # Platform placeholder
        {
            "type": "function",
            "function": {
                "name": "send_email",
                "description": "Another user tool",
                "parameters": {},
            },
        },
    ]

    # Process
    final_tools_array = resolve_and_prioritize_tools(incoming_tools)

    # Output
    print(json.dumps(final_tools_array, indent=2))
