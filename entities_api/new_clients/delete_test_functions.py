from client import OllamaClient

client = OllamaClient()

# List tools associated with the assistant
assistant_tools = client.tool_service.list_tools("asst_n7ngrdIhuweP4Ud6vMg4VV")

# Loop through each tool and delete it
for tool in assistant_tools['tools']:
    tool_id = tool['id']
    print(f"Deleting tool with ID: {tool_id}")
    client.tool_service.delete_tool(tool_id=tool_id)

print("All tools deleted successfully.")
