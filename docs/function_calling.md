# Function Calling

**Define the function**

```python
from entities_api import OllamaClient  
from entities_api.schemas import ToolFunction  # Import ToolFunction

# Initialize the client
client = OllamaClient()

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
    assistant_id=assistant_id
)

print(new_tool.id)

```


**Associate the new Tool with an Assistant**

```python

# Create assistant
assistant = client.assistant_service.create_assistant(
    user_id=user.id,
    name='Flighty',
    description='test_case',
    model='llama3.1',
    instructions='You are a helpful flight attendant'
)
print(f"Assistant created: ID: {assistant.id}")


# Associate the tool with an assistant
client.tool_service.associate_tool_with_assistant(
    tool_id=new_tool.id,
    assistant_id=assistant_id
)

print(f"New tool created: Name: {function_definition['function']['name']}, ID: {new_tool.id}")
print(new_tool)
```
The same tool can be associated to multiple [assistants](/docs/assistants.md).



**Updating a Tool**

**Deleting a tool**

```python
client.tool_service.disassociate_tool(
        tool_id=new_tool.id,
    )

```