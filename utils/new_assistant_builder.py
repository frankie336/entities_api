# Tool creation and association functions
from entities_api.clients.client import OllamaClient
from entities_api.schemas import ToolFunction  # Import ToolFunction
from entities_api.constants.assistant import DEFAULT_MODEL, BASE_ASSISTANT_INSTRUCTIONS
from entities_api.constants.assistant import BASE_TOOLS

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
        instructions=instructions,
        assistant_id="default"
    )
    print(f"Assistant created: ID: {assistant.id}")

    # Create and associate tools
    create_and_associate_tools(client, function_definitions, assistant.id)

    return assistant


# Example usage
if __name__ == "__main__":
    assistant = setup_assistant_with_tools(
        user_name='test_case',
        assistant_name='Nexa',
        assistant_description='Assistant',
        model=DEFAULT_MODEL,
        instructions=BASE_ASSISTANT_INSTRUCTIONS,
        function_definitions=BASE_TOOLS
    )
    print(f"\nSetup complete. Assistant ID: {assistant.id}")
