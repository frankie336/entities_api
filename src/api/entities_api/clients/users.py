import os
from typing import List

import httpx
from pydantic import ValidationError

from entities_api.services.logging_service import LoggingUtility
from entities_common import ValidationInterface

validation = ValidationInterface()
logging_utility = LoggingUtility()



class UserClient:
    def __init__(self, base_url=os.getenv("ASSISTANTS_BASE_URL"), api_key=None):
        self.base_url = base_url
        self.api_key = api_key
        self.client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"}
        )
        logging_utility.info("UserClient initialized with base_url: %s", self.base_url)

    def create_user(self, name: str) -> validation.UserRead:
        logging_utility.info("Creating user with name: %s", name)
        user_data = validation.UserCreate(name=name)
        try:
            response = self.client.post("/v1/users", json=user_data.model_dump())
            response.raise_for_status()
            validated_user = validation.UserRead.model_validate(response.json())
            logging_utility.info("User created successfully with id: %s", validated_user.id)
            return validated_user
        except (httpx.HTTPStatusError, ValidationError) as e:
            logging_utility.error("Error during user creation: %s", str(e))
            raise

    def retrieve_user(self, user_id: str) -> validation.UserRead:
        logging_utility.info("Retrieving user with id: %s", user_id)
        try:
            response = self.client.get(f"/v1/users/{user_id}")
            response.raise_for_status()
            validated_user = validation.UserRead.model_validate(response.json())
            logging_utility.info("User retrieved successfully")
            return validated_user
        except (httpx.HTTPStatusError, ValidationError) as e:
            logging_utility.error("Error during user retrieval: %s", str(e))
            raise

    def update_user(self, user_id: str, **updates) -> validation.UserRead:
        logging_utility.info("Updating user with id: %s", user_id)
        try:
            current_user = self.retrieve_user(user_id)
            user_data = current_user.model_dump()
            user_data.update(updates)

            validated_data = validation.UserUpdate(**user_data)
            response = self.client.put(
                f"/v1/users/{user_id}",
                json=validated_data.model_dump(exclude_unset=True)
            )
            response.raise_for_status()
            validated_response = validation.UserRead.model_validate(response.json())
            logging_utility.info("User updated successfully")
            return validated_response
        except (ValidationError, httpx.HTTPStatusError) as e:
            logging_utility.error("Error during user update: %s", str(e))
            raise

    def delete_user(self, user_id: str) -> validation.UserDeleteResponse:
        logging_utility.info("Deleting user with id: %s", user_id)
        try:
            response = self.client.delete(f"/v1/users/{user_id}")
            response.raise_for_status()
            validated_result = validation.UserDeleteResponse.model_validate(response.json())
            logging_utility.info("User deleted successfully")
            return validated_result
        except (httpx.HTTPStatusError, ValidationError) as e:
            logging_utility.error("Error during user deletion: %s", str(e))
            raise

    def list_assistants_by_user(self, user_id: str) -> List[validation.AssistantRead]:
        logging_utility.info("Retrieving assistants for user with id: %s", user_id)
        try:
            response = self.client.get(f"/v1/users/{user_id}/assistants")
            response.raise_for_status()
            assistants = response.json()
            validated_assistants = [validation.AssistantRead.model_validate(a) for a in assistants]
            logging_utility.info("Assistants retrieved successfully for user id: %s", user_id)
            return validated_assistants
        except (httpx.HTTPStatusError, ValidationError) as e:
            logging_utility.error("Error during assistants retrieval: %s", str(e))
            raise


if __name__ == "__main__":
    base_url = "http://localhost:9000"
    api_key = "your_api_key"

    logging_utility.info("Starting UserClient test")

    user_service = UserClient(base_url, api_key)

    try:
        new_user = user_service.create_user(name="Test User")
        logging_utility.info("Created user with ID: %s", new_user.id)

        retrieved_user = user_service.retrieve_user(new_user.id)
        logging_utility.info("Retrieved user: %s", retrieved_user)

        assistants = user_service.list_assistants_by_user(new_user.id)
        logging_utility.info("Assistants: %s", assistants)

    except Exception as e:
        logging_utility.error("UserClient test encountered an error: %s", str(e))
