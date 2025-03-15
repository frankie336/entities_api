import httpx
from typing import List, Dict, Any, Optional
from pydantic import ValidationError
from src.entities_api.services.logging_service import LoggingUtility
from src.entities_api.schemas import AssistantCreate, AssistantRead, AssistantUpdate

# Initialize logging utility
logging_utility = LoggingUtility()


class ClientAssistantService:
    def __init__(self, base_url="http://localhost:9000/", api_key=None):
        self.base_url = base_url
        self.api_key = api_key
        self.client = httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {api_key}"})
        logging_utility.info("ClientAssistantService initialized with base_url: %s", self.base_url)

    def create_assistant(self, model: str, name: str = "", description: str = "", instructions: str = "",
                         meta_data: Dict[str, Any] = None,
                         top_p: float = 1.0, temperature: float = 1.0, response_format: str = "auto",
                         assistant_id: Optional[str] = None) -> AssistantRead:
        """
        Create an assistant without requiring user_id, as the association is handled separately.
        """
        assistant_data = {
            "id": assistant_id,
            "name": name,
            "description": description,
            "model": model,
            "instructions": instructions,
            "meta_data": meta_data,
            "top_p": top_p,
            "temperature": temperature,
            "response_format": response_format
        }

        try:
            validated_data = AssistantCreate(**assistant_data)
            logging_utility.info("Creating assistant with model: %s, name: %s", model, name)

            response = self.client.post("/routers/assistants", json=validated_data.model_dump())
            response.raise_for_status()

            created_assistant = response.json()
            validated_response = AssistantRead(**created_assistant)
            logging_utility.info("Assistant created successfully with id: %s", validated_response.id)
            return validated_response
        except ValidationError as e:
            logging_utility.error("Validation error: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while creating assistant: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while creating assistant: %s", str(e))
            raise

    def retrieve_assistant(self, assistant_id: str) -> AssistantRead:
        logging_utility.info("Retrieving assistant with id: %s", assistant_id)
        try:
            response = self.client.get(f"/routers/assistants/{assistant_id}")
            response.raise_for_status()
            assistant = response.json()
            validated_data = AssistantRead(**assistant)
            logging_utility.info("Assistant retrieved successfully")
            return validated_data
        except ValidationError as e:
            logging_utility.error("Validation error: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while retrieving assistant: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while retrieving assistant: %s", str(e))
            raise

    def update_assistant(self, assistant_id: str, **updates) -> AssistantRead:
        logging_utility.info("Updating assistant with id: %s", assistant_id)
        try:
            updates.pop('id', None)
            updates.pop('assistant_id', None)

            validated_data = AssistantUpdate(**updates)

            response = self.client.put(f"/routers/assistants/{assistant_id}",
                                       json=validated_data.model_dump(exclude_unset=True))
            response.raise_for_status()
            updated_assistant = response.json()
            validated_response = AssistantRead(**updated_assistant)
            logging_utility.info("Assistant updated successfully")
            return validated_response
        except ValidationError as e:
            logging_utility.error("Validation error: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while updating assistant: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while updating assistant: %s", str(e))
            raise

    def delete_assistant(self, assistant_id: str) -> Dict[str, Any]:
        logging_utility.info("Deleting assistant with id: %s", assistant_id)
        try:
            response = self.client.delete(f"/routers/assistants/{assistant_id}")
            response.raise_for_status()
            result = response.json()
            logging_utility.info("Assistant deleted successfully")
            return result
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while deleting assistant: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while deleting assistant: %s", str(e))
            raise

    def associate_assistant_with_user(self, user_id: str, assistant_id: str) -> Dict[str, Any]:
        """
        Associate an assistant with a user by making a POST request to the appropriate endpoint.
        """
        logging_utility.info("Associating assistant with id: %s to user: %s", assistant_id, user_id)
        try:
            response = self.client.post(f"/routers/users/{user_id}/assistants/{assistant_id}")
            response.raise_for_status()
            logging_utility.info("Assistant %s associated with user %s successfully", assistant_id, user_id)
            return {"message": "Assistant associated with user successfully"}
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while associating assistant: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while associating assistant: %s", str(e))
            raise

    def disassociate_assistant_from_user(self, user_id: str, assistant_id: str) -> Dict[str, Any]:
        """
        Disassociate an assistant from a user by making a DELETE request to the appropriate endpoint.
        """
        logging_utility.info("Disassociating assistant with id: %s from user: %s", assistant_id, user_id)
        try:
            response = self.client.delete(f"/routers/users/{user_id}/assistants/{assistant_id}")
            response.raise_for_status()
            logging_utility.info("Assistant %s disassociated from user %s successfully", assistant_id, user_id)
            return {"message": "Assistant disassociated from user successfully"}
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while disassociating assistant: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while disassociating assistant: %s", str(e))
            raise


    def list_assistants_by_user(self, user_id: str) -> List[AssistantRead]:
        """
        Retrieve the list of assistants associated with a specific user.
        """
        logging_utility.info("Retrieving assistants for user id: %s", user_id)
        try:
            response = self.client.get(f"/routers/users/{user_id}/assistants")
            response.raise_for_status()
            assistants = response.json()
            validated_assistants = [AssistantRead(**assistant) for assistant in assistants]
            logging_utility.info("Assistants retrieved successfully for user id: %s", user_id)
            return validated_assistants
        except ValidationError as e:
            logging_utility.error("Validation error: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while retrieving assistants for user: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while retrieving assistants for user: %s", str(e))
            raise