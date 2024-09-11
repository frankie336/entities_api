import requests
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel
from entities_api.schemas import ActionRead, ActionUpdate, ActionCreate
from entities_api.services.identifier_service import IdentifierService

class ClientActionService:
    def __init__(self, base_url: str, api_key: str):
        """Initialize with base URL and API key for authentication."""
        self.base_url = base_url
        self.api_key = api_key

    def _headers(self) -> Dict[str, str]:
        """Helper method to return headers including the API key."""
        return {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

    def create_action(self, tool_name: str, run_id: str, function_args: Optional[Dict[str, Any]] = None,
                      expires_at: Optional[datetime] = None) -> ActionRead:
        """Create a new action using the provided tool_name, run_id, and function_args."""
        try:
            # Generate an action ID using IdentifierService
            action_id = IdentifierService.generate_action_id()

            # Create the payload with the generated action ID
            payload = ActionCreate(
                id=action_id,  # Use the generated action_id
                tool_name=tool_name,
                run_id=run_id,
                function_args=function_args or {},
                expires_at=expires_at
            )

            # Mock response for action creation (replace with actual request logic)
            response = {
                "id": action_id,
                "status": "success"
            }

            # Validate and return the action created
            validated_action = ActionRead(**response)
            return validated_action

        except Exception as e:
            raise ValueError(f"Unexpected error during action creation: {str(e)}")

    def get_action(self, action_id: str) -> ActionRead:
        """Retrieve a specific action by its ID."""
        try:
            # Make a GET request to retrieve the action with headers
            response = requests.get(f"{self.base_url}/actions/{action_id}", headers=self._headers())

            # Check for HTTP errors
            response.raise_for_status()

            # Parse the response JSON and validate it using ActionRead
            response_data = response.json()
            validated_action = ActionRead(**response_data)

            return validated_action

        except requests.exceptions.RequestException as e:
            # Handle errors related to the HTTP request
            raise ValueError(f"HTTP error during action retrieval: {str(e)}")

        except Exception as e:
            # Catch any other exceptions
            raise ValueError(f"Unexpected error during action retrieval: {str(e)}")

    def update_action(self, action_id: str, status: str, result: Optional[Dict[str, Any]] = None) -> ActionRead:
        """Update an action's status and result."""
        try:
            # Create the payload directly, validated using Pydantic ActionUpdate schema
            payload = ActionUpdate(status=status, result=result).dict(exclude_none=True)

            # Make a PUT request to update the action with headers
            response = requests.put(f"{self.base_url}/actions/{action_id}", json=payload, headers=self._headers())

            # Check for HTTP errors
            response.raise_for_status()

            # Parse the response JSON and validate it using ActionRead
            response_data = response.json()
            validated_action = ActionRead(**response_data)

            return validated_action

        except requests.exceptions.RequestException as e:
            # Handle errors related to the HTTP request
            raise ValueError(f"HTTP error during action update: {str(e)}")

        except Exception as e:
            # Catch any other exceptions
            raise ValueError(f"Unexpected error during action update: {str(e)}")

    def list_actions(self) -> List[ActionRead]:
        """List all actions."""
        try:
            # Make a GET request to retrieve all actions with headers
            response = requests.get(f"{self.base_url}/actions", headers=self._headers())

            # Check for HTTP errors
            response.raise_for_status()

            # Parse the response JSON and validate it using ActionList
            response_data = response.json()
            validated_actions = [ActionRead(**action) for action in response_data.get("actions", [])]

            return validated_actions

        except requests.exceptions.RequestException as e:
            # Handle errors related to the HTTP request
            raise ValueError(f"HTTP error during action listing: {str(e)}")

        except Exception as e:
            # Catch any other exceptions
            raise ValueError(f"Unexpected error during action listing: {str(e)}")

    def delete_action(self, action_id: str) -> Dict[str, Any]:
        """Delete a specific action by its ID."""
        try:
            # Make a DELETE request to remove the action with headers
            response = requests.delete(f"{self.base_url}/actions/{action_id}", headers=self._headers())

            # Check for HTTP errors
            response.raise_for_status()

            # Parse the response JSON (assume it's a success message)
            return response.json()

        except requests.exceptions.RequestException as e:
            # Handle errors related to the HTTP request
            raise ValueError(f"HTTP error during action deletion: {str(e)}")

        except Exception as e:
            # Catch any other exceptions
            raise ValueError(f"Unexpected error during action deletion: {str(e)}")
