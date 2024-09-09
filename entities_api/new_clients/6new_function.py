

def restructure_tools(assistant_tools):
    """Restructure the tools to handle dynamic function structures."""

    def parse_parameters(parameters):
        """Recursively parse parameters and handle different structures."""
        if isinstance(parameters, dict):
            parsed = {}
            for key, value in parameters.items():
                # If the value is a dict, recursively parse it
                if isinstance(value, dict):
                    parsed[key] = parse_parameters(value)
                else:
                    parsed[key] = value
            return parsed
        return parameters

    restructured_tools = []

    for tool in assistant_tools['tools']:
        function_info = tool['function']

        # Check if the 'function' key is nested and extract accordingly
        if 'function' in function_info:
            function_info = function_info['function']

        # Dynamically handle all function information
        restructured_tool = {
            'type': tool['type'],  # Keep the type information
            'name': function_info.get('name', 'Unnamed tool'),
            'description': function_info.get('description', 'No description provided'),
            'parameters': parse_parameters(function_info.get('parameters', {})),  # Recursively parse parameters
        }

        # Add the restructured tool to the list
        restructured_tools.append(restructured_tool)

    return restructured_tools


from client import OllamaClient
from entities_api.schemas import ToolFunction, ToolUpdate

client = OllamaClient()

# Create a new tool
new_tool = client.tool_service.create_tool(

    type='function',

    function={
                "type": "function",
                "function": {
                    "name": "getAnnouncedPrefixes",
                    "description": "Retrieves the announced prefixes for a given ASN",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "resource": {
                                "type": "string",
                                "description": "The ASN for which to retrieve the announced prefixes"
                            },
                            "starttime": {
                                "type": "string",
                                "description": "The start time for the query (ISO8601 or Unix timestamp)"
                            },
                            "endtime": {
                                "type": "string",
                                "description": "The end time for the query (ISO8601 or Unix timestamp)"
                            },
                            "min_peers_seeing": {
                                "type": "integer",
                                "description": "Minimum number of RIS peers seeing the prefix for it to be included in the results"
                            }
                        },
                        "required": ["resource"]
                    }
                }
            },

    assistant_id='asst_likBry4di6AglrEq3sQdUI'


)










# Associate the tool with an assistant
client.tool_service.associate_tool_with_assistant(
    tool_id=new_tool.id,
    assistant_id='asst_likBry4di6AglrEq3sQdUI'
)

print("New tool created:")
print(f"ID: {new_tool.id}")
print(new_tool)

# List tools associated with the assistant
assistant_tools = client.tool_service.list_tools("asst_likBry4di6AglrEq3sQdUI")


# Use the robust helper function to restructure the tools
restructured_tools = restructure_tools(assistant_tools)

# Output the restructured tools
for restructured_tool in restructured_tools:
    print(restructured_tool)
    print('-' * 40)

assistant_tools = client.tool_service.list_tools("asst_likBry4di6AglrEq3sQdUI")
