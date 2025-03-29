# entities_api/clients/client_actions_client.py
from datetime import datetime
from typing import Optional, Dict, Any, List
import httpx
from pydantic import ValidationError
from entities_common import ValidationInterface, UtilsInterface

validation = ValidationInterface()

from entities.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()

class ActionsClient:
    def __init__(self, base_url="http://localhost:9000/", api_key=None):
        """Initialize with base URL and API key for authentication."""
        self.client = httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {api_key}"})
        logging_utility.info("ActionsClient initialized with base_url: %s", base_url)

    def create_action(self, tool_name: str, run_id: str, function_args: Optional[Dict[str, Any]] = None,
                      expires_at: Optional[datetime] = None) -> validation.ActionRead:
        """Create a new action using the provided tool_name, run_id, and function_args."""
        try:
            action_id = UtilsInterface.IdentifierService.generate_action_id()

            # Convert expires_at to ISO 8601 string format if provided
            expires_at_iso = expires_at.isoformat() if expires_at else None

            payload = validation.ActionCreate(
                id=action_id,
                tool_name=tool_name,
                run_id=run_id,
                function_args=function_args or {},
                expires_at=None,
                status='pending'  # Ensure status is a string value
            ).dict()

            logging_utility.debug("Payload for action creation: %s", payload)

            # Sending the request
            response = self.client.post("/v1/actions", json=payload)

            # Log the response for debugging
            logging_utility.debug("Response Status Code: %s", response.status_code)
            logging_utility.debug("Response Body: %s", response.text)

            response.raise_for_status()

            response_data = response.json()
            validated_action = validation.ActionRead(**response_data)
            logging_utility.info("Action created successfully with ID: %s", action_id)
            return validated_action

        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error during action creation: %s", str(e))
            raise ValueError(f"HTTP error during action creation: {str(e)}")
        except Exception as e:
            logging_utility.error("Unexpected error during action creation: %s", str(e))
            raise ValueError(f"Unexpected error: {str(e)}")

    def get_action(self, action_id: str) -> validation.ActionRead:
        """
        Retrieve a specific action by its ID and return the validated `ActionRead` object.

        Args:
            action_id: The ID of the action to retrieve.

        Returns:
            ActionRead: The validated action data.

        Raises:
            ValueError: If the action is not found or if there is a validation or request error.
        """
        try:
            logging_utility.debug("Retrieving action with ID: %s", action_id)

            # Make the GET request to the endpoint
            response = self.client.get(f"/routers/actions/{action_id}")
            response.raise_for_status()  # Raise an error for bad status codes

            # Parse and validate the response
            response_data = response.json()
            validated_action = validation.ActionRead(**response_data)

            # Log success and debug details
            logging_utility.info("Action retrieved successfully with ID: %s", action_id)
            logging_utility.debug(
                "Validated action data: %s",
                validated_action.model_dump(mode="json")
            )

            return validated_action  # Return the validated Pydantic model

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                error_msg = f"Action {action_id} not found: {str(e)}"
                logging_utility.error(error_msg)
                raise ValueError(error_msg)
            logging_utility.error("HTTP error during action retrieval: %s", str(e))
            raise ValueError(f"HTTP error during action retrieval: {str(e)}")

        except ValidationError as e:
            logging_utility.error("Response validation failed: %s", str(e))
            logging_utility.debug("Invalid response data: %s", response_data)
            raise ValueError(f"Invalid action data format: {str(e)}")

        except httpx.RequestError as e:
            error_msg = f"Request error: {str(e)}"
            logging_utility.error(error_msg)
            raise ValueError(error_msg)

        except Exception as e:
            logging_utility.error("Unexpected error: %s", str(e))
            raise ValueError(f"Unexpected error: {str(e)}")

    def update_action(self, action_id: str, status: validation.ActionStatus,
                      result: Optional[Dict[str, Any]] = None) -> validation.ActionRead:
        """Update an action's status and result."""
        try:
            # Create the payload using the ActionUpdate schema
            payload = validation.ActionUpdate(status=status, result=result).dict(exclude_none=True)
            logging_utility.debug("Payload for action update: %s", payload)

            # Ensure the URL includes the /routers prefix
            response = self.client.put(f"/v1/actions/{action_id}", json=payload)
            response.raise_for_status()

            # Parse the response
            response_data = response.json()
            validated_action = validation.ActionRead(**response_data)
            logging_utility.info("Action updated successfully with ID: %s", action_id)
            return validated_action

        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error during action update: %s", str(e))
            raise ValueError(f"HTTP error during action update: {str(e)}")

    def get_actions_by_status(self, run_id: str, status: str = "pending") -> List[Dict[str, Any]]:
        """Retrieve actions by run_id and status."""
        try:
            logging_utility.debug(f"Retrieving actions for run_id: {run_id} with status: {status or 'not specified'}")

            # Make a GET request with run_id and optional status query parameter
            response = self.client.get(f"/v1/runs/{run_id}/actions/status", params={"status": status})
            response.raise_for_status()  # Raises an HTTPStatusError for bad responses

            # Optional safety check to ensure response is JSON
            if response.headers.get("Content-Type") == "application/json":
                response_data = response.json()
            else:
                logging_utility.error(f"Unexpected content type: {response.headers.get('Content-Type')}")
                raise ValueError(f"Unexpected content type: {response.headers.get('Content-Type')}")

            logging_utility.info(f"Actions retrieved successfully for run_id: {run_id} with status: {status}")
            return response_data  # Return raw JSON data

        except httpx.RequestError as e:
            logging_utility.error(f"An error occurred while requesting actions for run_id {run_id}: {str(e)}")
            raise ValueError(f"Request error: {str(e)}")
        except httpx.HTTPStatusError as e:
            logging_utility.error(
                f"HTTP error during actions retrieval for run_id {run_id} with status {status}: {str(e)}")
            raise ValueError(f"HTTP error during actions retrieval: {str(e)}")


    def get_pending_actions(self, run_id: str) -> List[Dict[str, Any]]:
        """
        Retrieve all pending actions with their function arguments, tool names, and run details.
        Filter by run_id (required).
        """
        try:
            logging_utility.debug("Retrieving pending actions with run_id: %s", run_id)

            # Make a GET request to the server to retrieve pending actions
            url = f"/v1/actions/pending/{run_id}"  # Embed run_id in the URL path

            response = self.client.get(url)  # No need to include params here
            response.raise_for_status()

            response_data = response.json()
            logging_utility.info("Pending actions retrieved successfully")
            return response_data  # Return raw JSON data

        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error during pending actions retrieval: %s", str(e))
            raise ValueError(f"HTTP error during pending actions retrieval: {str(e)}")
