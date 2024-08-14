# new_clients/message_client.py
from typing import List, Dict, Any, Optional

import httpx
from pydantic import ValidationError

from entities_api.schemas import MessageCreate, MessageRead, MessageUpdate  # Import the relevant Pydantic models
from entities_api.services.loggin_service import LoggingUtility

# Initialize logging utility
logging_utility = LoggingUtility()


class MessageService:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        self.client = httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {api_key}"})
        self.message_chunks: Dict[str, List[str]] = {}  # Temporary storage for message chunks
        logging_utility.info("MessageService initialized with base_url: %s", self.base_url)

    def create_message(self, thread_id: str, content: str, sender_id: str, role: str = 'user',
                       meta_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if meta_data is None:
            meta_data = {}

        message_data = {
            "thread_id": thread_id,
            "content": content,
            "role": role,
            "sender_id": sender_id,
            "meta_data": meta_data
        }

        logging_utility.info("Creating message for thread_id: %s, role: %s", thread_id, role)
        try:
            validated_data = MessageCreate(**message_data)  # Validate data using Pydantic model
            response = self.client.post("/v1/messages", json=validated_data.dict())
            response.raise_for_status()
            created_message = response.json()
            logging_utility.info("Message created successfully with id: %s", created_message.get('id'))
            return created_message
        except ValidationError as e:
            logging_utility.error("Validation error: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while creating message: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while creating message: %s", str(e))
            raise

    def retrieve_message(self, message_id: str) -> MessageRead:
        logging_utility.info("Retrieving message with id: %s", message_id)
        try:
            response = self.client.get(f"/v1/messages/{message_id}")
            response.raise_for_status()
            message = response.json()
            validated_message = MessageRead(**message)  # Validate data using Pydantic model
            logging_utility.info("Message retrieved successfully")
            return validated_message
        except ValidationError as e:
            logging_utility.error("Validation error: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while retrieving message: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while retrieving message: %s", str(e))
            raise

    def update_message(self, message_id: str, **updates) -> MessageRead:
        logging_utility.info("Updating message with id: %s", message_id)
        try:
            validated_data = MessageUpdate(**updates)  # Validate data using Pydantic model
            response = self.client.put(f"/v1/messages/{message_id}", json=validated_data.dict(exclude_unset=True))
            response.raise_for_status()
            updated_message = response.json()
            validated_response = MessageRead(**updated_message)  # Validate response using Pydantic model
            logging_utility.info("Message updated successfully")
            return validated_response
        except ValidationError as e:
            logging_utility.error("Validation error: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while updating message: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while updating message: %s", str(e))
            raise

    def list_messages(self, thread_id: str, limit: int = 20, order: str = "asc") -> List[Dict[str, Any]]:
        logging_utility.info("Listing messages for thread_id: %s, limit: %d, order: %s", thread_id, limit, order)
        params = {
            "limit": limit,
            "order": order
        }
        try:
            response = self.client.get(f"/v1/threads/{thread_id}/messages", params=params)
            response.raise_for_status()
            messages = response.json()
            validated_messages = [MessageRead(**message) for message in
                                  messages]  # Validate response using Pydantic model
            logging_utility.info("Retrieved %d messages", len(validated_messages))
            return [message.dict() for message in validated_messages]  # Convert Pydantic models to dictionaries
        except ValidationError as e:
            logging_utility.error("Validation error: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while listing messages: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while listing messages: %s", str(e))
            raise

    def get_formatted_messages(self, thread_id: str, system_message: str = "") -> List[Dict[str, Any]]:
        logging_utility.info("Getting formatted messages for thread_id: %s", thread_id)
        logging_utility.info("Using system message: %s", system_message)
        try:
            response = self.client.get(f"/v1/threads/{thread_id}/formatted_messages")
            response.raise_for_status()
            formatted_messages = response.json()

            if not isinstance(formatted_messages, list):
                raise ValueError("Expected a list of messages")

            logging_utility.debug("Initial formatted messages: %s", formatted_messages)

            # Replace the system message if one already exists, otherwise insert it at the beginning
            if formatted_messages and formatted_messages[0].get('role') == 'system':
                formatted_messages[0]['content'] = system_message
                logging_utility.debug("Replaced existing system message with: %s", system_message)
            else:
                formatted_messages.insert(0, {
                    "role": "system",
                    "content": system_message
                })
                logging_utility.debug("Inserted new system message: %s", system_message)

            logging_utility.info("Formatted messages after insertion: %s", formatted_messages)
            logging_utility.info("Retrieved %d formatted messages", len(formatted_messages))
            return formatted_messages
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logging_utility.error("Thread not found: %s", thread_id)
                raise ValueError(f"Thread not found: {thread_id}")
            else:
                logging_utility.error("HTTP error occurred: %s", str(e))
                raise RuntimeError(f"HTTP error occurred: {e}")
        except Exception as e:
            logging_utility.error("An error occurred: %s", str(e))
            raise RuntimeError(f"An error occurred: {str(e)}")

    def delete_message(self, message_id: str) -> Dict[str, Any]:
        logging_utility.info("Deleting message with id: %s", message_id)
        try:
            response = self.client.delete(f"/v1/messages/{message_id}")
            response.raise_for_status()
            result = response.json()
            logging_utility.info("Message deleted successfully")
            return result
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while deleting message: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while deleting message: %s", str(e))
            raise

    def save_assistant_message_chunk(self, thread_id: str, content: str, is_last_chunk: bool = False) -> Optional[Dict[str, Any]]:
        logging_utility.info("Saving assistant message chunk for thread_id: %s, is_last_chunk: %s", thread_id, is_last_chunk)
        message_data = {
            "thread_id": thread_id,
            "content": content,
            "role": "assistant",
            "sender_id": "assistant",
            "meta_data": {}
        }

        try:
            response = self.client.post("/v1/messages/assistant", json=message_data)
            response.raise_for_status()
            saved_message = response.json()
            logging_utility.info("Assistant message chunk saved successfully")
            return saved_message
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while saving assistant message chunk: %s", str(e))
            return None
        except Exception as e:
            logging_utility.error("An error occurred while saving assistant message chunk: %s", str(e))
            return None
