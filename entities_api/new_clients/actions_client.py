import httpx
from typing import Optional, List
from pydantic import ValidationError
from entities_api.schemas import ActionCreate, ActionRead, ActionUpdate, ActionList
from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()

class ClientActionService:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        self.client = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=10.0  # Timeout set for 10 seconds
        )
        logging_utility.info("ClientActionService initialized with base_url: %s", self.base_url)

    def __del__(self):
        self.client.close()

    def create_action(self, action_data: ActionCreate) -> ActionRead:
        """Create a new action."""
        logging_utility.info("Creating action for tool_id: %s, run_id: %s", action_data.tool_id, action_data.run_id)
        try:
            response = self.client.post("/v1/actions", json=action_data.model_dump())
            response.raise_for_status()
            created_action = response.json()
            validated_action = ActionRead.model_validate(created_action)
            logging_utility.info("Action created successfully with ID: %s", validated_action.id)
            return validated_action
        except ValidationError as e:
            logging_utility.error("Validation error during action creation: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error during action creation: %s | Response: %s", str(e), e.response.text)
            raise
        except Exception as e:
            logging_utility.error("Unexpected error during action creation: %s", str(e))
            raise

    def get_action(self, action_id: str) -> ActionRead:
        """Retrieve an action by its ID."""
        logging_utility.info("Retrieving action with ID: %s", action_id)
        try:
            response = self.client.get(f"/v1/actions/{action_id}")
            response.raise_for_status()
            action_data = response.json()
            validated_action = ActionRead.model_validate(action_data)
            logging_utility.info("Action retrieved successfully with ID: %s", validated_action.id)
            return validated_action
        except ValidationError as e:
            logging_utility.error("Validation error during action retrieval: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error during action retrieval: %s | Response: %s", str(e), e.response.text)
            raise
        except Exception as e:
            logging_utility.error("Unexpected error during action retrieval: %s", str(e))
            raise

    def update_action_status(self, action_id: str, action_update: ActionUpdate) -> ActionRead:
        """Update the status of an action."""
        logging_utility.info("Updating action with ID: %s", action_id)
        try:
            response = self.client.put(f"/v1/actions/{action_id}", json=action_update.model_dump(exclude_unset=True))
            response.raise_for_status()
            updated_action = response.json()
            validated_action = ActionRead.model_validate(updated_action)
            logging_utility.info("Action with ID: %s updated successfully", action_id)
            return validated_action
        except ValidationError as e:
            logging_utility.error("Validation error during action update: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error during action update: %s | Response: %s", str(e), e.response.text)
            raise
        except Exception as e:
            logging_utility.error("Unexpected error during action update: %s", str(e))
            raise

    def list_actions_for_run(self, run_id: str) -> List[ActionRead]:
        """List all actions associated with a specific run."""
        logging_utility.info("Listing actions for run_id: %s", run_id)
        try:
            response = self.client.get(f"/v1/runs/{run_id}/actions")
            response.raise_for_status()
            action_list = response.json()
            validated_action_list = [ActionRead.model_validate(action) for action in action_list['actions']]
            logging_utility.info("Found %d actions for run_id: %s", len(validated_action_list), run_id)
            return validated_action_list
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error during listing actions: %s | Response: %s", str(e), e.response.text)
            raise
        except Exception as e:
            logging_utility.error("Unexpected error during listing actions: %s", str(e))
            raise

    def delete_action(self, action_id: str) -> None:
        """Delete an action by its ID."""
        logging_utility.info("Deleting action with ID: %s", action_id)
        try:
            response = self.client.delete(f"/v1/actions/{action_id}")
            response.raise_for_status()
            logging_utility.info("Action with ID: %s deleted successfully", action_id)
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error during action deletion: %s | Response: %s", str(e), e.response.text)
            raise
        except Exception as e:
            logging_utility.error("Unexpected error during action deletion: %s", str(e))
            raise
