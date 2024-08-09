import httpx
from typing import Dict, Any
from services.loggin_service import LoggingUtility
from pydantic import ValidationError
from api.v1.schemas import UserRead, UserCreate, UserUpdate, UserDeleteResponse

# Initialize logging utility
logging_utility = LoggingUtility()


class UserService:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        self.client = httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {api_key}"})
        logging_utility.info("UserService initialized with base_url: %s", self.base_url)

    def create_user(self, name: str) -> UserRead:
        logging_utility.info("Creating user with name: %s", name)
        user_data = UserCreate(name=name)
        try:
            response = self.client.post("/v1/users", json=user_data.model_dump())
            response.raise_for_status()
            created_user = response.json()
            validated_user = UserRead(**created_user)
            logging_utility.info("User created successfully with id: %s", validated_user.id)
            return validated_user
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while creating user: %s", str(e))
            logging_utility.error("Status code: %d, Response text: %s", e.response.status_code, e.response.text)
            raise
        except Exception as e:
            logging_utility.error("An error occurred while creating user: %s", str(e))
            raise

    def retrieve_user(self, user_id: str) -> UserRead:
        logging_utility.info("Retrieving user with id: %s", user_id)
        try:
            response = self.client.get(f"/v1/users/{user_id}")
            response.raise_for_status()
            user = response.json()
            validated_user = UserRead(**user)
            logging_utility.info("User retrieved successfully")
            return validated_user
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while retrieving user: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while retrieving user: %s", str(e))
            raise

    def update_user(self, user_id: str, **updates) -> UserRead:
        logging_utility.info("Updating user with id: %s", user_id)
        try:
            current_user = self.retrieve_user(user_id)
            user_data = current_user.model_dump()
            user_data.update(updates)

            validated_data = UserUpdate(**user_data)  # Validate data using Pydantic model
            response = self.client.put(f"/v1/users/{user_id}", json=validated_data.model_dump(exclude_unset=True))
            response.raise_for_status()
            updated_user = response.json()
            validated_response = UserRead(**updated_user)  # Validate response using Pydantic model
            logging_utility.info("User updated successfully")
            return validated_response
        except ValidationError as e:
            logging_utility.error("Validation error: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while updating user: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while updating user: %s", str(e))
            raise

    def delete_user(self, user_id: str) -> UserDeleteResponse:
        logging_utility.info("Deleting user with id: %s", user_id)
        try:
            response = self.client.delete(f"/v1/users/{user_id}")
            response.raise_for_status()
            result = response.json()
            validated_result = UserDeleteResponse(**result)
            logging_utility.info("User deleted successfully")
            return validated_result
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while deleting user: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while deleting user: %s", str(e))
            raise


if __name__ == "__main__":
    # Replace with your actual base URL and API key
    base_url = "http://localhost:9000"
    api_key = "your_api_key"

    logging_utility.info("Starting UserService test")

    # Initialize the client
    user_service = UserService(base_url, api_key)

    try:
        # Create a user
        new_user = user_service.create_user(name="Test User")
        user_id = new_user.id
        logging_utility.info("Created user with ID: %s", user_id)

        # Retrieve the user
        retrieved_user = user_service.retrieve_user(user_id)
        logging_utility.info("Retrieved user: %s", retrieved_user)

        # Update the user
        # updated_user = user_service.update_user(user_id, name="Updated Test User")
        # logging_utility.info("Updated user: %s", updated_user)

        # Delete the user
        # delete_result = user_service.delete_user(user_id)
        # logging_utility.info("Delete result: %s", delete_result)

    except Exception as e:
        logging_utility.error("An error occurred during UserService test: %s", str(e))
