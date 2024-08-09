import httpx
from typing import List, Dict, Any, Optional
from pydantic import ValidationError
from services.loggin_service import LoggingUtility

from api.v1.schemas import AssistantCreate, AssistantRead, AssistantUpdate

# Initialize logging utility
logging_utility = LoggingUtility()


class AssistantService:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        self.client = httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {api_key}"})
        logging_utility.info("AssistantService initialized with base_url: %s", self.base_url)

    def create_assistant(self, user_id: str, model: str, name: str = "", description: str = "", instructions: str = "",
                         tools: List[Dict[str, Any]] = None) -> AssistantRead:
        if tools is None:
            tools = []

        assistant_data = {
            "user_id": user_id,
            "name": name,
            "description": description,
            "model": model,
            "instructions": instructions,
            "tools": tools,
            "meta_data": {},
            "top_p": 1.0,
            "temperature": 1.0,
            "response_format": "auto"
        }

        try:
            validated_data = AssistantCreate(**assistant_data)  # Validate data using Pydantic model
            logging_utility.info("Creating assistant with model: %s, name: %s", model, name)

            response = self.client.post("/v1/assistants", json=validated_data.model_dump())

            response.raise_for_status()
            created_assistant = response.json()
            validated_response = AssistantRead(**created_assistant)  # Validate response using Pydantic model
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
            response = self.client.get(f"/v1/assistants/{assistant_id}")
            response.raise_for_status()
            assistant = response.json()
            validated_data = AssistantRead(**assistant)  # Validate data using Pydantic model
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
            # Fetch the current state of the assistant
            current_assistant = self.retrieve_assistant(assistant_id)

            # Merge the updates with the current state
            assistant_data = current_assistant.model_dump()
            assistant_data.update(updates)

            # Validate the merged data
            validated_data = AssistantUpdate(**assistant_data)  # Validate data using Pydantic model

            response = self.client.put(f"/v1/assistants/{assistant_id}",
                                       json=validated_data.model_dump(exclude_unset=True))
            response.raise_for_status()
            updated_assistant = response.json()
            validated_response = AssistantRead(**updated_assistant)  # Validate response using Pydantic model
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

    def list_assistants(self, limit: int = 20, order: str = "asc") -> List[AssistantRead]:
        logging_utility.info("Listing assistants with limit: %d, order: %s", limit, order)
        params = {
            "limit": limit,
            "order": order
        }
        try:
            response = self.client.get("/v1/assistants", params=params)
            response.raise_for_status()
            assistants = response.json()
            validated_assistants = [AssistantRead(**assistant) for assistant in assistants]  # Validate response using Pydantic model
            logging_utility.info("Retrieved %d assistants", len(validated_assistants))
            return validated_assistants
        except ValidationError as e:
            logging_utility.error("Validation error: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while listing assistants: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while listing assistants: %s", str(e))
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


if __name__ == "__main__":
    # Replace with your actual base URL and API key
    base_url = "http://localhost:9000"
    api_key = "your_api_key"

    logging_utility.info("Starting AssistantService test")

    # Initialize the client
    assistant_service = AssistantService(base_url, api_key)

    try:
        # Create an assistant
        user_id = "user_zFu5VPLgtpzGIqMN30eccb"
        created_assistant = assistant_service.create_assistant(user_id=user_id, model="gpt-3", name="Test Assistant")
        logging_utility.info("Created assistant: %s", created_assistant)

        # Retrieve the assistant
        retrieved_assistant = assistant_service.retrieve_assistant(created_assistant.id)
        logging_utility.info("Retrieved assistant: %s", retrieved_assistant)

        # Update the assistant with only the fields we want to change
        updated_assistant = assistant_service.update_assistant(retrieved_assistant.id, name="Updated Test Assistant")
        logging_utility.info("Updated assistant: %s", updated_assistant)

    except Exception as e:
        logging_utility.error("An error occurred during AssistantService test: %s", str(e))
