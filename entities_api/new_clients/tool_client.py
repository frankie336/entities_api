import httpx
from typing import List, Optional
from pydantic import ValidationError
from entities_api.schemas import ToolCreate, ToolRead, ToolUpdate
from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()


class ClientToolService:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        self.client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10.0  # Add a timeout of 10 seconds
        )
        logging_utility.info("ClientToolService initialized with base_url: %s", self.base_url)

    def __del__(self):
        # Close the client when the instance is destroyed to prevent resource leaks
        self.client.close()

    def create_tool(self, **tool_data) -> ToolRead:
        logging_utility.info("Creating new tool")
        try:
            tool = ToolCreate(**tool_data)
            response = self.client.post("/v1/tools", json=tool.model_dump())
            response.raise_for_status()
            created_tool = response.json()
            validated_tool = ToolRead.model_validate(created_tool)
            logging_utility.info("Tool created successfully with id: %s", validated_tool.id)
            return validated_tool
        except ValidationError as e:
            logging_utility.error("Validation error during tool creation: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error during tool creation: %s | Response: %s", str(e), e.response.text)
            raise
        except Exception as e:
            logging_utility.error("Unexpected error during tool creation: %s", str(e))
            raise

    def associate_tool_with_assistant(self, tool_id: str, assistant_id: str) -> None:
        logging_utility.info(f"Associating tool {tool_id} with assistant {assistant_id}")
        try:
            response = self.client.post(f"/v1/assistants/{assistant_id}/tools/{tool_id}")
            response.raise_for_status()
            logging_utility.info(f"Tool {tool_id} associated with assistant {assistant_id} successfully")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error during tool-assistant association: %s | Response: %s", str(e), e.response.text)
            raise
        except Exception as e:
            logging_utility.error("Unexpected error during tool-assistant association: %s", str(e))
            raise

    def get_tool(self, tool_id: str) -> ToolRead:
        logging_utility.info("Retrieving tool with id: %s", tool_id)
        try:
            response = self.client.get(f"/v1/tools/{tool_id}")
            response.raise_for_status()
            tool = response.json()
            validated_tool = ToolRead.model_validate(tool)
            logging_utility.info("Tool retrieved successfully")
            return validated_tool
        except ValidationError as e:
            logging_utility.error("Validation error during tool retrieval: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error during tool retrieval: %s | Response: %s", str(e), e.response.text)
            raise
        except Exception as e:
            logging_utility.error("Unexpected error during tool retrieval: %s", str(e))
            raise

    def update_tool(self, tool_id: str, tool_update: ToolUpdate) -> ToolRead:
        logging_utility.info("Updating tool with id: %s", tool_id)
        try:
            response = self.client.put(f"/v1/tools/{tool_id}", json=tool_update.model_dump(exclude_unset=True))
            response.raise_for_status()
            updated_tool = response.json()
            validated_tool = ToolRead.model_validate(updated_tool)
            logging_utility.info("Tool updated successfully")
            return validated_tool
        except ValidationError as e:
            logging_utility.error("Validation error during tool update: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error during tool update: %s | Response: %s", str(e), e.response.text)
            raise
        except Exception as e:
            logging_utility.error("Unexpected error during tool update: %s", str(e))
            raise

    def delete_tool(self, tool_id: str) -> None:
        logging_utility.info("Deleting tool with id: %s", tool_id)
        try:
            response = self.client.delete(f"/v1/tools/{tool_id}")
            response.raise_for_status()
            logging_utility.info("Tool deleted successfully")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error during tool deletion: %s | Response: %s", str(e), e.response.text)
            raise
        except Exception as e:
            logging_utility.error("Unexpected error during tool deletion: %s", str(e))
            raise

    def parse_parameters(self, parameters):
        """Recursively parse parameters and handle different structures."""
        if isinstance(parameters, dict):
            parsed = {}
            for key, value in parameters.items():
                if isinstance(value, dict):
                    parsed[key] = self.parse_parameters(value)
                else:
                    parsed[key] = value
            return parsed
        return parameters

    def restructure_tools(self, assistant_tools):
        """Restructure the tools to match the target structure."""

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

            # Restructure the tool to match the target structure
            restructured_tool = {
                'type': tool['type'],  # Keep the type information
                'function': {
                    'name': function_info.get('name', 'Unnamed tool'),
                    'description': function_info.get('description', 'No description provided'),
                    'parameters': parse_parameters(function_info.get('parameters', {})),  # Recursively parse parameters
                }
            }

            # Add the restructured tool to the list
            restructured_tools.append(restructured_tool)

        return restructured_tools

    def list_tools(self, assistant_id: Optional[str] = None, restructure: bool = False) -> List[dict]:
        """List tools for a given assistant and optionally restructure them."""
        url = f"/v1/assistants/{assistant_id}/tools" if assistant_id else "/v1/tools"
        logging_utility.info("Listing tools")
        try:
            response = self.client.get(url)
            response.raise_for_status()
            tools = response.json()  # Return raw JSON data as a list of dictionaries

            logging_utility.info("Retrieved %d tools", len(tools['tools']))

            # Optionally restructure tools
            if restructure:
                tools = self.restructure_tools(tools)

            return tools
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error while listing tools: %s | Response: %s", str(e), e.response.text)
            raise
        except Exception as e:
            logging_utility.error("Unexpected error while listing tools: %s", str(e))
            raise
