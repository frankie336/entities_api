import httpx
from typing import List, Dict, Any, Optional
from pydantic import ValidationError
from entities_api.schemas import ToolCreate, ToolRead, ToolUpdate
from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()


class ClientToolService:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        self.client = httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {api_key}"})
        logging_utility.info("ClientToolService initialized with base_url: %s", self.base_url)

    def create_tool(self, assistant_id: str, **tool_data) -> ToolRead:
        logging_utility.info("Creating new tool for assistant_id: %s", assistant_id)
        try:
            tool = ToolCreate(**tool_data)
            response = self.client.post(f"/v1/assistants/{assistant_id}/tools", json=tool.dict())
            response.raise_for_status()
            created_tool = response.json()
            validated_tool = ToolRead(**created_tool)
            logging_utility.info("Tool created successfully with id: %s", validated_tool.id)
            return validated_tool
        except ValidationError as e:
            logging_utility.error("Validation error: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while creating tool: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while creating tool: %s", str(e))
            raise
    def get_tool(self, tool_id: str) -> ToolRead:
        logging_utility.info("Retrieving tool with id: %s", tool_id)
        try:
            response = self.client.get(f"/v1/tools/{tool_id}")
            response.raise_for_status()
            tool = response.json()
            validated_tool = ToolRead(**tool)
            logging_utility.info("Tool retrieved successfully")
            return validated_tool
        except ValidationError as e:
            logging_utility.error("Validation error: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while retrieving tool: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while retrieving tool: %s", str(e))
            raise

    def update_tool(self, tool_id: str, tool_update: ToolUpdate) -> ToolRead:
        logging_utility.info("Updating tool with id: %s", tool_id)
        try:
            response = self.client.put(f"/v1/tools/{tool_id}", json=tool_update.dict(exclude_unset=True))
            response.raise_for_status()
            updated_tool = response.json()
            validated_tool = ToolRead(**updated_tool)
            logging_utility.info("Tool updated successfully")
            return validated_tool
        except ValidationError as e:
            logging_utility.error("Validation error: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while updating tool: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while updating tool: %s", str(e))
            raise

    def delete_tool(self, tool_id: str) -> None:
        logging_utility.info("Deleting tool with id: %s", tool_id)
        try:
            response = self.client.delete(f"/v1/tools/{tool_id}")
            response.raise_for_status()
            logging_utility.info("Tool deleted successfully")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while deleting tool: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while deleting tool: %s", str(e))
            raise

    def list_tools(self, assistant_id: str) -> List[ToolRead]:
        logging_utility.info("Listing tools for assistant_id: %s", assistant_id)
        try:
            response = self.client.get(f"/v1/assistants/{assistant_id}/tools")
            response.raise_for_status()
            tools = response.json()
            validated_tools = [ToolRead(**tool) for tool in tools]
            logging_utility.info("Retrieved %d tools", len(validated_tools))
            return validated_tools
        except ValidationError as e:
            logging_utility.error("Validation error: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while listing tools: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while listing tools: %s", str(e))
            raise