from entities_api import OllamaClient
from entities_api.schemas import ToolFunction, ToolUpdate  # Import ToolFunction and ToolUpdate

# Initialize the client
client = OllamaClient()

# Create a user
user = client.user_service.create_user(name='test_user')
print(f"User created: ID: {user.id}")

# Create an assistant
assistant = client.assistant_service.create_assistant(
    user_id=user.id,
    name='Flighty',
    description='test_case',
    model='llama3.1',
    instructions='You are a helpful flight attendant'
)
print(f"Assistant created: ID: {assistant.id}")

# Define the function definition
function_definition = {
    "type": "function",
    "function": {
        "name": "get_flight_times",
        "description": "Get the flight times between two cities.",
        "parameters": {
            "type": "object",
            "properties": {
                "departure": {
                    "type": "string",
                    "description": "The departure city (airport code)."
                },
                "arrival": {
                    "type": "string",
                    "description": "The arrival city (airport code)."
                }
            },
            "required": ["departure", "arrival"]
        }
    }
}

# Wrap the function definition in ToolFunction
tool_function = ToolFunction(function=function_definition['function'])

# Create a new tool with the name included
new_tool = client.tool_service.create_tool(
    name=function_definition['function']['name'],  # Pass the tool name explicitly
    type='function',
    function=tool_function,  # Pass the wrapped ToolFunction
    assistant_id=assistant.id
)
print(f"New Tool created: ID: {new_tool.id}")

# Associate the tool with an assistant
client.tool_service.associate_tool_with_assistant(
    tool_id=new_tool.id,
    assistant_id=assistant.id
)

# Define the new function definition for updating
new_function_definition = {
    "type": "function",
    "function": {
        "name": "get_flight_times",
        "description": "Retrieve updated flight times between two cities.",
        "parameters": {
            "type": "object",
            "properties": {
                "departure": {
                    "type": "string",
                    "description": "The departure city (airport code)."
                },
                "arrival": {
                    "type": "string",
                    "description": "The arrival city (airport code)."
                },
                "date": {
                    "type": "string",
                    "description": "The date for the flight times (YYYY-MM-DD)."
                }
            },
            "required": ["departure", "arrival", "date"]
        }
    }
}

# Specify the tool ID to update
tool_id = new_tool.id

# Create a ToolUpdate instance with the new function definition
tool_update = ToolUpdate(function=ToolFunction(function=new_function_definition['function']))

# Update the tool
try:
    updated_tool = client.tool_service.update_tool(tool_id=tool_id, tool_update=tool_update)
    print(f"Tool updated successfully: {updated_tool}")
except Exception as e:
    print(f"Failed to update tool: {str(e)}")
