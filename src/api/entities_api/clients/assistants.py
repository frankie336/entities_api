import os
from typing import Optional, List, Dict, Any

import httpx
from pydantic import ValidationError
from entities_common import ValidationInterface

validation = ValidationInterface()

from entities_api.services.logging_service import LoggingUtility

# Initialize logging utility
logging_utility = LoggingUtility()


class AssistantsClient:

    def __init__(self, base_url=os.getenv("ASSISTANTS_BASE_URL"), api_key=None):
        self.base_url = base_url
        self.api_key = api_key
        self.client = httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {api_key}"})
        logging_utility.info("AssistantsClient initialized with base_url: %s", self.base_url)


    logging_utility = LoggingUtility()

    def create_assistant(
            self,
            model: str,
            name: str = "",
            description: str = "",
            instructions: str = "",
            tools: Optional[List] = None,  # Accept tools as a raw list
            meta_data: Dict[str, Any] = None,
            top_p: float = 1.0,
            temperature: float = 1.0,
            response_format: str = "auto",
            assistant_id: Optional[str] = None
    ) -> validation.AssistantRead:
        """
        Create an assistant without requiring a user_id, as the association
        is handled separately.
        """
        assistant_data = {
            "id": assistant_id,
            "name": name,
            "description": description,
            "model": model,
            "instructions": instructions,
            "tools": tools,
            "meta_data": meta_data,
            "top_p": top_p,
            "temperature": temperature,
            "response_format": response_format,
        }

        try:
            # Validate using AssistantCreate to ensure data integrity.
            try:
                validated_data = validation.AssistantCreate(**assistant_data)
            except ValidationError as e:
                logging_utility.error("Validation error: %s", e.json())
                raise ValueError(f"Validation error: {e}")

            # Log the request data for debugging purposes.
            logging_utility.debug("Request data: %s", assistant_data)
            logging_utility.info("Creating assistant with model: %s, name: %s", model, name)

            # Make the POST request to create the assistant.
            response = self.client.post("/v1/assistants", json=validated_data.model_dump())

            # Log the raw response for debugging.
            logging_utility.debug("Response: %s", response.text)
            response.raise_for_status()

            # Parse the response JSON and validate it against AssistantRead.
            if response.status_code == 200:
                created_assistant = response.json()  # Only parse if the response is successful
                validated_response = validation.AssistantRead(**created_assistant)
                logging_utility.info("Assistant created successfully with id: %s", validated_response.id)
                return validated_response
            else:
                logging_utility.error("Failed to create assistant, response: %s", response.text)
                raise ValueError(f"Failed to create assistant, status: {response.status_code}")

        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while creating assistant: %s", str(e))
            logging_utility.error("Response content: %s", e.response.text)  # Log the response content for debugging
            raise
        except Exception as e:
            logging_utility.error("An error occurred while creating assistant: %s", str(e))
            raise

    def retrieve_assistant(self, assistant_id: str) -> validation.AssistantRead:
        logging_utility.info("Retrieving assistant with id: %s", assistant_id)
        try:
            response = self.client.get(f"/v1/assistants/{assistant_id}")
            response.raise_for_status()
            assistant = response.json()
            validated_data = validation.AssistantRead(**assistant)
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

    def update_assistant(self, assistant_id: str, **updates) -> validation.AssistantRead:
        logging_utility.info("Updating assistant with id: %s", assistant_id)
        try:
            updates.pop('id', None)
            updates.pop('assistant_id', None)

            validated_data = validation.AssistantUpdate(**updates)

            response = self.client.put(f"/v1/assistants/{assistant_id}",
                                       json=validated_data.model_dump(exclude_unset=True))
            response.raise_for_status()
            updated_assistant = response.json()
            validated_response = validation.AssistantRead(**updated_assistant)
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
            response = self.client.delete(f"/v1/assistants/{assistant_id}")
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
            response = self.client.post(f"/v1/users/{user_id}/assistants/{assistant_id}")
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
            response = self.client.delete(f"/v1/users/{user_id}/assistants/{assistant_id}")
            response.raise_for_status()
            logging_utility.info("Assistant %s disassociated from user %s successfully", assistant_id, user_id)
            return {"message": "Assistant disassociated from user successfully"}
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while disassociating assistant: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while disassociating assistant: %s", str(e))
            raise


    def list_assistants_by_user(self, user_id: str) -> List[validation.AssistantRead]:
        """
        Retrieve the list of assistants associated with a specific user.
        """
        logging_utility.info("Retrieving assistants for user id: %s", user_id)
        try:
            response = self.client.get(f"/v1/users/{user_id}/assistants")
            response.raise_for_status()
            assistants = response.json()
            validated_assistants = [validation.AssistantRead(**assistant) for assistant in assistants]
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