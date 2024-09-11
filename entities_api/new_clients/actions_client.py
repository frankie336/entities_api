import httpx
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel
from entities_api.schemas import ActionRead, ActionUpdate, ActionCreate
from entities_api.services.identifier_service import IdentifierService
from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()


class ClientActionService:
    def __init__(self, base_url: str, api_key: str):
        """Initialize with base URL and API key for authentication."""
        self.client = httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {api_key}"})
        logging_utility.info("ClientActionService initialized with base_url: %s", base_url)

    def create_action(self, tool_name: str, run_id: str, function_args: Optional[Dict[str, Any]] = None,
                      expires_at: Optional[datetime] = None) -> ActionRead:
        """Create a new action using the provided tool_name, run_id, and function_args."""
        try:
            action_id = IdentifierService.generate_action_id()

            # Convert expires_at to ISO 8601 string format if provided
            expires_at_iso = expires_at.isoformat() if expires_at else None

            payload = ActionCreate(
                id=action_id,
                tool_name=tool_name,
                run_id=run_id,
                function_args=function_args or {},
                expires_at=expires_at_iso  # Use the ISO 8601 format for datetime
            ).dict()

            logging_utility.debug("Payload for action creation: %s", payload)

            # Correct the URL to include /v1 prefix
            response = self.client.post("/v1/actions", json=payload)
            response.raise_for_status()

            response_data = response.json()
            validated_action = ActionRead(**response_data)
            logging_utility.info("Action created successfully with ID: %s", action_id)
            return validated_action

        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error during action creation: %s", str(e))
            raise ValueError(f"HTTP error during action creation: {str(e)}")

    def get_action(self, action_id: str) -> ActionRead:
        """Retrieve a specific action by its ID."""
        try:
            logging_utility.debug("Retrieving action with ID: %s", action_id)

            response = self.client.get(f"/actions/{action_id}")
            response.raise_for_status()

            response_data = response.json()
            validated_action = ActionRead(**response_data)
            logging_utility.info("Action retrieved successfully with ID: %s", action_id)
            return validated_action

        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error during action retrieval: %s", str(e))
            raise ValueError(f"HTTP error during action retrieval: {str(e)}")

    def update_action(self, action_id: str, status: str, result: Optional[Dict[str, Any]] = None) -> ActionRead:
        """Update an action's status and result."""
        try:
            payload = ActionUpdate(status=status, result=result).dict(exclude_none=True)
            logging_utility.debug("Payload for action update: %s", payload)

            response = self.client.put(f"/actions/{action_id}", json=payload)
            response.raise_for_status()

            response_data = response.json()
            validated_action = ActionRead(**response_data)
            logging_utility.info("Action updated successfully with ID: %s", action_id)
            return validated_action

        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error during action update: %s", str(e))
            raise ValueError(f"HTTP error during action update: {str(e)}")
