# entities_api/clients/client_actions_client.py
from datetime import datetime
from typing import Optional, Dict, Any, List

import httpx

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

    def get_action(self, action_id: str) -> Dict[str, Any]:
        """Retrieve a specific action by its ID without Pydantic validation."""
        try:
            logging_utility.debug("Retrieving action with ID: %s", action_id)

            response = self.client.get(f"/v1/actions/{action_id}")
            response.raise_for_status()

            response_data = response.json()
            logging_utility.info("Action retrieved successfully with ID: %s", action_id)
            return response_data  # Return raw JSON data

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logging_utility.error("Action with ID %s not found: %s", action_id, str(e))
                return None  # Return None or handle it as you wish
            else:
                logging_utility.error("HTTP error during action retrieval: %s", str(e))
                raise ValueError(f"HTTP error during action retrieval: {str(e)}")

    def update_action(self, action_id: str, status: str, result: Optional[Dict[str, Any]] = None) -> ActionRead:
        """Update an action's status and result."""
        try:
            payload = ActionUpdate(status=status, result=result).dict(exclude_none=True)
            logging_utility.debug("Payload for action update: %s", payload)

            # Ensure the URL includes the /v1 prefix
            response = self.client.put(f"/v1/actions/{action_id}", json=payload)
            response.raise_for_status()

            response_data = response.json()
            validated_action = ActionRead(**response_data)
            logging_utility.info("Action updated successfully with ID: %s", action_id)
            return validated_action

        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error during action update: %s", str(e))
            raise ValueError(f"HTTP error during action update: {str(e)}")

    def get_actions_by_status(self, run_id: str, status: Optional[str] = "pending") -> List[Dict[str, Any]]:
        """Retrieve actions by run_id and status."""
        try:
            logging_utility.debug(f"Retrieving actions for run_id: {run_id} with status: {status}")

            # Make a GET request with run_id and optional status query parameter
            response = self.client.get(f"/v1/runs/{run_id}/actions/status", params={"status": status})
            response.raise_for_status()

            response_data = response.json()
            logging_utility.info(f"Actions retrieved successfully for run_id: {run_id} with status: {status}")
            return response_data  # Return raw JSON data

        except httpx.HTTPStatusError as e:
            logging_utility.error(f"HTTP error during actions retrieval for run_id {run_id} with status {status}: {str(e)}")
            raise ValueError(f"HTTP error during actions retrieval: {str(e)}")

    def delete_action(self, action_id: str) -> None:
        """Delete an action by its ID."""
        logging_utility.info(f"Deleting action with ID: {action_id}")
        try:
            # Ensure the URL includes the /v1 prefix
            response = self.client.delete(f"/v1/actions/{action_id}")
            response.raise_for_status()

            logging_utility.info(f"Action with ID {action_id} deleted successfully.")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logging_utility.error(f"Action with ID {action_id} not found: {str(e)}")
                raise ValueError(f"Action with ID {action_id} not found")
            else:
                logging_utility.error(f"HTTP error during action deletion: {str(e)}")
                raise ValueError(f"HTTP error during action deletion: {str(e)}")

