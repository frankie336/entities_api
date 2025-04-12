import os
from typing import List, Optional  # Added Optional

import httpx
from dotenv import load_dotenv
from projectdavid_common import UtilsInterface, ValidationInterface
from pydantic import ValidationError

# Use a clearer alias if ValidationInterface is used elsewhere too
ent_validator = ValidationInterface()

load_dotenv()
logging_utility = UtilsInterface.LoggingUtility()


class UsersClient:
    def __init__(self, base_url: str, api_key: str):
        """
        Initialize the UsersClient.

        Args:
            base_url (str): The base URL for the user service API (e.g., "http://localhost:8000").
            api_key (str): The API key for authentication.
        """
        if not base_url:
            raise ValueError("base_url must be provided.")
        if not api_key:
            raise ValueError("api_key must be provided for authentication.")

        self.base_url = base_url
        self.api_key = api_key
        # Use X-API-Key header for authentication
        headers = {"X-API-Key": self.api_key}
        self.client = httpx.Client(base_url=self.base_url, headers=headers)
        logging_utility.info("UsersClient initialized with base_url: %s", self.base_url)

    def create_user(
        self, user_data: ent_validator.UserCreate
    ) -> ent_validator.UserRead:
        """
        Creates a new user.

        Args:
            user_data: A Pydantic model containing the user creation details
                       (e.g., email, full_name, oauth_provider).

        Returns:
            A Pydantic model representing the created user.

        Raises:
            ValueError: If validation fails before sending.
            httpx.HTTPStatusError: For API-level errors (4xx, 5xx).
            Exception: For other unexpected errors.
        """
        logging_utility.info(
            "Attempting to create user with email: %s", user_data.email
        )
        try:
            # Validate input data before sending (Pydantic does this on instantiation)
            payload = user_data.model_dump()  # Use model_dump for Pydantic v2
            response = self.client.post("/v1/users", json=payload)
            response.raise_for_status()  # Raise exception for 4xx/5xx responses
            created_user_json = response.json()
            # Validate the response conforms to UserRead
            validated_user = ent_validator.UserRead.model_validate(created_user_json)
            logging_utility.info(
                "User created successfully with id: %s", validated_user.id
            )
            return validated_user
        except ValidationError as e:
            # Should ideally not happen if user_data is already a valid UserCreate model,
            # but good practice for response validation.
            logging_utility.error(
                "Pydantic validation error during user creation response: %s", e.json()
            )
            raise ValueError(f"Invalid response data from API: {e}") from e
        except httpx.HTTPStatusError as e:
            logging_utility.error(
                "HTTP error occurred while creating user: Status %s, Response: %s",
                e.response.status_code,
                e.response.text,
            )
            raise  # Re-raise the original exception
        except Exception as e:
            logging_utility.error(
                "An unexpected error occurred while creating user: %s",
                str(e),
                exc_info=True,
            )
            raise  # Re-raise the original exception

    def retrieve_user(self, user_id: str) -> ent_validator.UserRead:
        """
        Retrieves a user by their internal ID.

        Args:
            user_id: The unique identifier of the user.

        Returns:
            A Pydantic model representing the retrieved user.

        Raises:
            httpx.HTTPStatusError: If user not found (404) or other API errors.
            Exception: For other unexpected errors.
        """
        logging_utility.info("Retrieving user with id: %s", user_id)
        try:
            response = self.client.get(f"/v1/users/{user_id}")
            response.raise_for_status()
            user_json = response.json()
            validated_user = ent_validator.UserRead.model_validate(user_json)
            logging_utility.info("User retrieved successfully: %s", user_id)
            return validated_user
        except httpx.HTTPStatusError as e:
            logging_utility.error(
                "HTTP error occurred while retrieving user %s: Status %s, Response: %s",
                user_id,
                e.response.status_code,
                e.response.text,
            )
            raise
        except ValidationError as e:
            logging_utility.error(
                "Pydantic validation error during user retrieval response: %s", e.json()
            )
            raise ValueError(f"Invalid response data from API: {e}") from e
        except Exception as e:
            logging_utility.error(
                "An unexpected error occurred while retrieving user %s: %s",
                user_id,
                str(e),
                exc_info=True,
            )
            raise

    def update_user(
        self, user_id: str, user_update_data: ent_validator.UserUpdate
    ) -> ent_validator.UserRead:
        """
        Updates an existing user. Sends only the fields present in user_update_data.

        Args:
            user_id: The ID of the user to update.
            user_update_data: A Pydantic UserUpdate model containing the fields to update.

        Returns:
            A Pydantic model representing the updated user.

        Raises:
            ValueError: If validation fails before sending.
            httpx.HTTPStatusError: For API-level errors (4xx, 5xx).
            Exception: For other unexpected errors.
        """
        logging_utility.info("Attempting to update user with id: %s", user_id)
        try:
            # Send only fields that are set in the Pydantic model
            payload = user_update_data.model_dump(exclude_unset=True)
            if not payload:
                logging_utility.warning(
                    "Update user called for %s with no fields to update.", user_id
                )
                # Optionally return the current user state or raise an error
                return self.retrieve_user(
                    user_id
                )  # Return current state if no update needed

            # Use PUT or PATCH depending on API design. Assuming PUT handles partial updates here.
            response = self.client.put(f"/v1/users/{user_id}", json=payload)
            response.raise_for_status()
            updated_user_json = response.json()
            validated_user = ent_validator.UserRead.model_validate(updated_user_json)
            logging_utility.info("User updated successfully: %s", user_id)
            return validated_user
        except ValidationError as e:
            # Validation error on the input model or the response model
            logging_utility.error(
                "Pydantic validation error during user update: %s", e.json()
            )
            raise ValueError(f"Invalid data for update or invalid response: {e}") from e
        except httpx.HTTPStatusError as e:
            logging_utility.error(
                "HTTP error occurred while updating user %s: Status %s, Response: %s",
                user_id,
                e.response.status_code,
                e.response.text,
            )
            raise
        except Exception as e:
            logging_utility.error(
                "An unexpected error occurred while updating user %s: %s",
                user_id,
                str(e),
                exc_info=True,
            )
            raise

    def delete_user(self, user_id: str) -> bool:
        """
        Deletes a user by their internal ID.

        Args:
            user_id: The unique identifier of the user to delete.

        Returns:
            True if deletion was successful (API returned 204), False otherwise.

        Raises:
            httpx.HTTPStatusError: For API errors other than 404 (e.g., 401, 500).
                                   A 404 might be treated as "already deleted".
            Exception: For other unexpected errors.
        """
        logging_utility.info("Attempting to delete user with id: %s", user_id)
        try:
            response = self.client.delete(f"/v1/users/{user_id}")

            # Check for successful deletion (204 No Content is standard)
            if response.status_code == 204:
                logging_utility.info("User deleted successfully: %s", user_id)
                return True
            # Check if already deleted (404 Not Found) - treat as success in idempotency?
            elif response.status_code == 404:
                logging_utility.warning(
                    "Attempted to delete user %s, but they were not found (already deleted?).",
                    user_id,
                )
                return True  # Or False depending on desired behavior
            # For other errors, raise the exception
            else:
                response.raise_for_status()  # Raise for other 4xx/5xx errors
                # Should not reach here if raise_for_status works correctly
                logging_utility.error(
                    "Received unexpected status code %s during user deletion: %s",
                    response.status_code,
                    response.text,
                )
                return False

        except httpx.HTTPStatusError as e:
            # Catch 404 separately if we didn't handle it above
            if e.response.status_code == 404:
                logging_utility.warning(
                    "Attempted to delete user %s, but they were not found (already deleted?).",
                    user_id,
                )
                return True  # Or False
            logging_utility.error(
                "HTTP error occurred while deleting user %s: Status %s, Response: %s",
                user_id,
                e.response.status_code,
                e.response.text,
            )
            raise  # Re-raise other HTTP errors
        except Exception as e:
            logging_utility.error(
                "An unexpected error occurred while deleting user %s: %s",
                user_id,
                str(e),
                exc_info=True,
            )
            raise

    def list_assistants_by_user(
        self, user_id: str
    ) -> List[ent_validator.AssistantRead]:
        """
        Retrieves the list of assistants associated with a specific user.

        Args:
            user_id: The unique identifier of the user.

        Returns:
            A list of Pydantic models representing the user's assistants.

        Raises:
            httpx.HTTPStatusError: If the user is not found or other API errors.
            Exception: For other unexpected errors.
        """
        logging_utility.info("Retrieving assistants for user with id: %s", user_id)
        try:
            # Ensure the API endpoint exists (e.g., defined in users_router.py)
            response = self.client.get(f"/v1/users/{user_id}/assistants")
            response.raise_for_status()
            assistants_json = response.json()

            # Validate that the response is a list and each item is a valid AssistantRead
            validated_assistants = [
                ent_validator.AssistantRead.model_validate(assistant)
                for assistant in assistants_json  # Assuming response.json() returns a list
            ]
            logging_utility.info(
                "Retrieved %d assistants successfully for user id: %s",
                len(validated_assistants),
                user_id,
            )
            return validated_assistants
        except httpx.HTTPStatusError as e:
            logging_utility.error(
                "HTTP error occurred while retrieving assistants for user %s: Status %s, Response: %s",
                user_id,
                e.response.status_code,
                e.response.text,
            )
            raise
        except ValidationError as e:
            logging_utility.error(
                "Pydantic validation error during assistant list response: %s", e.json()
            )
            raise ValueError(f"Invalid response data from API: {e}") from e
        except Exception as e:
            logging_utility.error(
                "An unexpected error occurred while retrieving assistants for user %s: %s",
                user_id,
                str(e),
                exc_info=True,
            )
            raise
