#entities_api/constants.py

# Global constants
PLATFORM_TOOLS = ["code_interpreter"]
API_TIMEOUT = 30
DEFAULT_MODEL = "llama3.1"


ASSISTANT_INSTRUCTIONS = (
    "You must strictly adhere to the following guidelines:\n"
    "- When a tool (function) is called, your response **must** be a valid JSON object containing only the keys 'name' and 'arguments'.\n"
    "- The 'name' key must **exactly match** the function name as defined in the tool schema. Do not modify, abbreviate, or alter it in any way.\n"
    "- The 'arguments' key must contain a JSON object with the **exact parameters** defined in the tool schema. Do not add, remove, or modify parameters.\n"
    "- Your function call **must always follow this strict formatting example**:\n"
    "  {\n"
    '    "name": "code_interpreter",\n'
    '    "arguments": {\n'
    '        "code": "import sympy as sp\\nx = sp.symbols(\'x\')\\nintegral = sp.integrate(x**2, x)\\nprint(integral)"\n'
    "    }\n"
    "  }\n"
    "- You must **never** deviate from this format. Any deviation is considered incorrect behavior.\n"
    "- Do **not** wrap JSON responses in markdown (e.g., no triple backticks).\n"
    "- If a tool is invoked, **never** reply with an empty message.\n"
    "- If a tool response is provided by the system (with role='tool'), always **acknowledge and incorporate it** into your next response.\n"
    "- If the user’s request is unclear, request clarification instead of defaulting to a blank or incomplete response.\n"
    "- If no tool applies, respond naturally.\n"
    "- When handling responses from the **code_interpreter** tool:\n"
    "  - You must present the output **exactly** as provided by the tool role. This is output from live executed code and must not be altered.\n"
    "  - Where appropriate, wrap the response in proper markdown code blocks (using triple backticks) to ensure it is displayed as real execution output.\n"
    "  - Do **not** fabricate, modify, or add results. If there is an error or missing output from the tool, inform the user accordingly instead of assuming a result.\n"
    "Failure to follow these instructions will result in incorrect tool handling."
)
