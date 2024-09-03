from client import OllamaClient

client = OllamaClient()


# Create a new tool
new_tool = client.tool_service.create_tool(type="function",
                                           function={"name": "get_weather", "description": "Get weather information"},
                                           assistant_id="asst_t14mLPRT0N9s9ddPDUJmVT"
                                           )




# Get a tool
tool = client.tool_service.get_tool("tool_ycOYNDvFrPIj8SofRmcju4")
print(tool)

from client import OllamaClient
from entities_api.schemas import ToolFunction, ToolUpdate

client = OllamaClient()

# First, let's define the updates we want to make
tool_updates = ToolUpdate(
    type="function",  # You can update the type if needed
    function=ToolFunction(
        name="get_detailed_weather",
        description="Get detailed weather information including forecast",
        parameters={
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "The city and state, e.g. San Francisco, CA"
                },
                "days": {
                    "type": "integer",
                    "description": "The number of days to forecast"
                }
            },
            "required": ["location"]
        }
    )
)

# Now, let's update the tool
try:
    updated_tool = client.tool_service.update_tool(
        tool_id="tool_ycOYNDvFrPIj8SofRmcju4",  # Replace with the actual tool ID you want to update
        tool_update=tool_updates
    )
    print("Tool updated successfully:")
    print(f"ID: {updated_tool.id}")
    print(f"Type: {updated_tool.type}")
    print(f"Function Name: {updated_tool.function.name}")
    print(f"Function Description: {updated_tool.function.description}")
    print(f"Function Parameters: {updated_tool.function.parameters}")
except Exception as e:
    print(f"An error occurred while updating the tool: {str(e)}")

