from typing import List, Dict, Any, Optional

import httpx
from pydantic import ValidationError
from entities_common import ValidationInterface

validation = ValidationInterface()

from entities_api.services.logging_service import LoggingUtility

# Initialize logging utility
logging_utility = LoggingUtility()


class ThreadsClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        self.client = httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {api_key}"})
        logging_utility.info("ThreadsClient initialized with base_url: %s", self.base_url)

    def create_user(self, name: str) -> validation.UserRead:
        logging_utility.info("Creating user with name: %s", name)
        user_data = validation.UserCreate(name=name).model_dump()
        try:
            response = self.client.post("/v1/users", json=user_data)
            response.raise_for_status()
            created_user = response.json()
            validated_user = validation.UserRead(**created_user)  # Validate data using Pydantic model
            logging_utility.info("User created successfully with id: %s", validated_user.id)
            return validated_user
        except ValidationError as e:
            logging_utility.error("Validation error: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while creating user: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while creating user: %s", str(e))
            raise

    def create_thread(self, participant_ids: List[str], meta_data: Optional[Dict[str, Any]] = None) -> validation.ThreadRead:
        if meta_data is None:
            meta_data = {}

        thread_data = validation.ThreadCreate(participant_ids=participant_ids, meta_data=meta_data).model_dump()
        logging_utility.info("Creating thread with %d participants", len(participant_ids))
        try:
            response = self.client.post("/v1/threads", json=thread_data)
            response.raise_for_status()
            created_thread = response.json()
            validated_thread = validation.ThreadRead(**created_thread)  # Validate data using Pydantic model
            logging_utility.info("Thread created successfully with id: %s", validated_thread.id)
            return validated_thread
        except ValidationError as e:
            logging_utility.error("Validation error: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while creating thread: %s", str(e))
            logging_utility.error("Status code: %d, Response text: %s", e.response.status_code, e.response.text)
            raise
        except Exception as e:
            logging_utility.error("An error occurred while creating thread: %s", str(e))
            raise

    def retrieve_thread(self, thread_id: str) -> validation.ThreadRead:
        logging_utility.info("Retrieving thread with id: %s", thread_id)
        try:
            response = self.client.get(f"/v1/threads/{thread_id}")
            response.raise_for_status()
            thread = response.json()
            validated_thread = validation.ThreadRead(**thread)  # Validate data using Pydantic model
            logging_utility.info("Thread retrieved successfully")
            return validated_thread
        except ValidationError as e:
            logging_utility.error("Validation error: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while retrieving thread: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while retrieving thread: %s", str(e))
            raise

    def update_thread(self, thread_id: str, **updates) -> validation.ThreadReadDetailed:

        logging_utility.info(f"Updating thread with id: {thread_id}")

        try:
            validated_updates = validation.ThreadUpdate(**updates)
            response = self.client.post(f"/v1/threads/{thread_id}", json=validated_updates.model_dump())
            response.raise_for_status()
            updated_thread = response.json()
            return validation.ThreadReadDetailed(**updated_thread)
        except httpx.HTTPStatusError as e:
            logging_utility.error(f"HTTP error occurred while updating thread: {e}")
            logging_utility.error(f"Response content: {e.response.content}")
            raise
        except Exception as e:
            logging_utility.error(f"An error occurred while updating thread: {e}")
            raise

    def update_thread_metadata(self, thread_id: str, new_metadata: Dict[str, Any]) -> validation.ThreadRead:
        """
        Updates the metadata for a specific thread by its ID.
        """
        logging_utility.info("Updating metadata for thread with id: %s", thread_id)
        try:
            # Retrieve the existing thread to ensure it exists and get current metadata
            thread = self.retrieve_thread(thread_id)
            current_metadata = thread.meta_data

            # Update the metadata
            current_metadata.update(new_metadata)

            # Send the update request
            return self.update_thread(thread_id, meta_data=current_metadata)
        except ValidationError as e:
            logging_utility.error("Validation error while updating thread metadata: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while updating thread metadata: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while updating thread metadata: %s", str(e))
            raise

    def list_threads(self, user_id: str) -> List[str]:
        logging_utility.info("Listing threads for user with id: %s", user_id)
        try:
            response = self.client.get(f"/v1/users/{user_id}/threads")
            response.raise_for_status()
            thread_ids = response.json()
            validated_thread_ids = validation.ThreadIds(**thread_ids)  # Validate data using Pydantic model
            logging_utility.info("Retrieved %d thread ids", len(validated_thread_ids.thread_ids))
            return validated_thread_ids.thread_ids
        except ValidationError as e:
            logging_utility.error("Validation error: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while listing threads: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while listing threads: %s", str(e))
            raise

    def delete_thread(self, thread_id: str) -> None:
        logging_utility.info("Deleting thread with id: %s", thread_id)
        try:
            response = self.client.delete(f"/v1/threads/{thread_id}")
            response.raise_for_status()
            logging_utility.info("Thread deleted successfully")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while deleting thread: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while deleting thread: %s", str(e))
            raise


if __name__ == "__main__":
    # Replace with your actual base URL and API key
    base_url = "http://localhost:9000"
    api_key = "your_api_key"

    logging_utility.info("Starting ThreadsClient test")

    # Initialize the client
    thread_service = ThreadsClient(base_url, api_key)

    try:
        # Create users
        user1 = thread_service.create_user(name="User 1")
        user2 = thread_service.create_user(name="User 2")

        # Get user IDs
        user1_id = user1.id
        user2_id = user2.id

        # Create a thread
        new_thread = thread_service.create_thread(participant_ids=[user1_id, user2_id], meta_data={"topic": "Test Thread"})

        # Retrieve the thread ID from the response
        thread_id = new_thread.id

        logging_utility.info("Created thread with ID: %s", thread_id)

        # Optionally, retrieve the created thread to verify
        retrieved_thread = thread_service.retrieve_thread(thread_id)
        logging_utility.info("Retrieved thread: %s", retrieved_thread)

        # Update the thread metadata
        updated_thread = thread_service.update_thread_metadata(thread_id, new_metadata={"topic": "Updated Topic"})

        logging_utility.info("Updated thread metadata: %s", updated_thread.meta_data)

        # Optionally, retrieve the updated thread to verify changes
        updated_retrieved_thread = thread_service.retrieve_thread(thread_id)
        logging_utility.info("Retrieved updated thread: %s", updated_retrieved_thread.meta_data)

    except Exception as e:
        logging_utility.error("An error occurred during ThreadsClient test: %s", str(e))
