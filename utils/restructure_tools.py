# utils/restructure_tools.py

from entities_api.new_clients.client import OllamaClient

client = OllamaClient()



# List tools without restructuring
tools = client.tool_service.list_tools(assistant_id="asst_UePiOTkZHDufuNNgceEWbv", restructure=False)
print("Tools without restructuring:", tools)

# List tools with restructuring
restructured_tools = client.tool_service.list_tools(assistant_id="asst_UePiOTkZHDufuNNgceEWbv", restructure=True)
print("Restructured tools:", restructured_tools)