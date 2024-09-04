import time

from client import OllamaClient
from entities_api.schemas import ToolFunction, ToolUpdate

client = OllamaClient()

# Create a new tool
new_tool = client.tool_service.create_tool(
    type="function",
    function={"name": "get_weather", "description": "Get weather information"},
    assistant_id="asst_n7ngrdIhuweP4Ud6vMg4VV"
)
print("New tool created:")
print(f"ID: {new_tool.id}")
print(f"Type: {new_tool.type}")
print(f"Function Name: {new_tool.function.name}")
print(f"Function Description: {new_tool.function.description}")
print(new_tool)




# Get a tool
tool = client.tool_service.get_tool(tool_id=new_tool.id)
print("\nRetrieved tool:")
print(tool)
# breaks here


tool_updates = ToolUpdate(
    type="function",
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


try:
    updated_tool = client.tool_service.update_tool(
        tool_id=new_tool.id,
        tool_update=tool_updates
    )
    print("\nTool updated successfully:")
    print(f"ID: {updated_tool.id}")
    print(f"Type: {updated_tool.type}")
    print(f"Function Name: {updated_tool.function.name}")
    print(f"Function Description: {updated_tool.function.description}")
    print(f"Function Parameters: {updated_tool.function.parameters}")
except Exception as e:
    print(f"An error occurred while updating the tool: {str(e)}")





# List tools for a specific assistant
assistant_tools = client.tool_service.list_tools("asst_n7ngrdIhuweP4Ud6vMg4VV")

#time.sleep(1000)
#print("\nTools for assistant:")
#for tool in assistant_tools:
    #print(f"- {tool.id}: {tool.function.name}")





# Delete a tool
# client.tool_service.delete_tool("tool_ycOYNDvFrPIj8SofRmcju4")
#print("\nTool deleted successfully")