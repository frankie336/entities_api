# Tool creation and association functions
from entities_api.clients.client import OllamaClient
from entities_api.schemas import ToolFunction  # Import ToolFunction


def create_and_associate_tools(client, function_definitions, assistant_id):
    for func_def in function_definitions:
        # Extract the tool name from the function definition
        tool_name = func_def['function']['name']

        # Wrap the function definition in ToolFunction
        tool_function = ToolFunction(function=func_def['function'])

        # Create a new tool with the name included
        new_tool = client.tool_service.create_tool(
            name=tool_name,  # Pass the tool name explicitly
            type='function',
            function=tool_function,  # Pass the wrapped ToolFunction
            assistant_id=assistant_id
        )

        # Associate the tool with an assistant
        client.tool_service.associate_tool_with_assistant(
            tool_id=new_tool.id,
            assistant_id=assistant_id
        )

        print(f"New tool created: Name: {tool_name}, ID: {new_tool.id}")
        print(new_tool)


def setup_assistant_with_tools(user_name, assistant_name, assistant_description,
                               model, instructions, function_definitions):
    client = OllamaClient()

    # Create user
    user = client.user_service.create_user(name=user_name)
    userid = user.id
    print(f"User created: ID: {userid}")

    # Create assistant
    assistant = client.assistant_service.create_assistant(
        name=assistant_name,
        description=assistant_description,
        model=model,
        instructions=instructions
    )
    print(f"Assistant created: ID: {assistant.id}")

    # Create and associate tools
    create_and_associate_tools(client, function_definitions, assistant.id)

    return assistant


# Example usage
if __name__ == "__main__":
    function_definitions = [
        {
            "type": "function",
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
            "type": "function",
            "function": {
                "name": "get_flight_times",
                "description": "Get the flight times between two cities",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "departure": {"type": "string", "description": "The departure city (airport code)"},
                        "arrival": {"type": "string", "description": "The arrival city (airport code)"}
                    },
                    "required": ["departure", "arrival"]
                }
            }
        }

    ]

    assistant = setup_assistant_with_tools(
        user_name='test_case',
        assistant_name='Nexa',
        assistant_description='Assistant',
        model='llama3.1',


        instructions="You must strictly adhere to the following guidelines:\n"
        "- When a tool (function) is called, your response **must** be a valid JSON object containing only the keys 'name' and 'arguments'.\n"
        "- Do **not** wrap JSON responses in markdown (e.g., no triple backticks).\n"
        "- If a tool is invoked, **never** reply with an empty message.\n"
        "- If a tool response is provided by the system (with role='tool'), always **acknowledge and incorporate it** into your next response.\n"
        "- If the user’s request is unclear, request clarification instead of defaulting to a blank or incomplete response.\n"
        "- If no tool applies, respond naturally.\n"
        "Failure to follow these instructions will result in incorrect tool handling."
        ,

        function_definitions=function_definitions


    )

    print(f"\nSetup complete. Assistant ID: {assistant.id}")
