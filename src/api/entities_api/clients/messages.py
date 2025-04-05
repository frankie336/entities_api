# clients/messages.py
from typing import List, Dict, Any, Optional

import httpx
from pydantic import ValidationError
from entities_common import ValidationInterface

validation = ValidationInterface()



from entities_api.services.logging_service import LoggingUtility

# Initialize logging utility
logging_utility = LoggingUtility()


class MessagesClient:
    def __init__(self, base_url="http://localhost:9000/", api_key=None):
        self.base_url = base_url
        self.api_key = api_key
        self.client = httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {api_key}"})
        self.message_chunks: Dict[str, List[str]] = {}  # Temporary storage for message chunks
        logging_utility.info("MessagesClient initialized with base_url: %s", self.base_url)

    def create_message(self, thread_id: str, content: str, assistant_id: str,
                       role: str = 'user', meta_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if meta_data is None:
            meta_data = {}

        message_data = {
            "thread_id": thread_id,
            "content": content,
            "role": role,
            "assistant_id": assistant_id,
            "meta_data": meta_data
        }

        logging_utility.info("Creating message for thread_id: %s, role: %s", thread_id, role)
        try:
            validated_data = validation.MessageCreate(**message_data)  # Validate data using Pydantic model
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


    def retrieve_message(self, message_id: str) -> validation.MessageRead:
        logging_utility.info("Retrieving message with id: %s", message_id)
        try:
            response = self.client.get(f"/v1/messages/{message_id}")
            response.raise_for_status()
            message = response.json()
            validated_message = validation.MessageRead(**message)  # Validate data using Pydantic model
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

    def update_message(self, message_id: str, **updates) -> validation.MessageRead:
        logging_utility.info("Updating message with id: %s", message_id)
        try:
            validated_data = validation.MessageUpdate(**updates)  # Validate data using Pydantic model
            response = self.client.put(f"/v1/messages/{message_id}", json=validated_data.dict(exclude_unset=True))
            response.raise_for_status()
            updated_message = response.json()
            validated_response = validation.MessageRead(**updated_message)  # Validate response using Pydantic model
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
            validated_messages = [validation.MessageRead(**message) for message in
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

            # Ensure tool messages conform to expected structure
            for msg in formatted_messages:
                if msg.get("role") == "tool":
                    if "tool_call_id" not in msg or "content" not in msg:
                        logging_utility.warning("Malformed tool message detected: %s", msg)
                        raise ValueError(f"Malformed tool message: {msg}")

            # Replace system message if one exists, otherwise insert it
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

    def get_messages_without_system_message(self, thread_id: str) -> List[Dict[str, Any]]:
        logging_utility.info("Getting formatted messages for thread_id: %s", thread_id)
        try:
            response = self.client.get(f"/v1/threads/{thread_id}/formatted_messages")
            response.raise_for_status()
            formatted_messages = response.json()

            if not isinstance(formatted_messages, list):
                raise ValueError("Expected a list of messages")

            logging_utility.debug("Retrieved formatted messages: %s", formatted_messages)

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

    def save_assistant_message_chunk(
            self,
            thread_id: str,
            role: str,
            content: str,
            assistant_id: str,  # Required parameter
            sender_id: str,  # Required parameter
            is_last_chunk: bool = False,
            meta_data: Optional[Dict[str, Any]] = None  # Optional metadata
    ) -> Optional[validation.MessageRead]:  # Return MessageRead for final chunk, None for non-final chunks
        """
        Save a message chunk from the assistant, with support for streaming and dynamic roles.

        Args:
            thread_id: The ID of the thread the message belongs to
            role: The role of the message sender (e.g., 'assistant', 'user', 'system')
            content: The message content
            assistant_id: The ID of the assistant sending the message
            sender_id: The ID of the user or system initiating the message
            is_last_chunk: Whether this is the final chunk in a stream
            meta_data: Optional metadata dictionary

        Returns:
            MessageRead: For the final chunk, returns the saved message details.
            None: For non-final chunks, returns None.
        """
        logging_utility.info(
            "Saving assistant message chunk for thread_id: %s, role: %s, is_last_chunk: %s",
            thread_id,
            role,
            is_last_chunk,
        )

        # Prepare the request payload
        message_data = {
            "thread_id": thread_id,
            "content": content,
            "role": role,
            "assistant_id": assistant_id,
            "sender_id": sender_id,
            "is_last_chunk": is_last_chunk,
            "meta_data": meta_data or {}  # Use empty dict if None
        }

        try:
            # Make the API request
            response = self.client.post("/v1/messages/assistant", json=message_data)
            response.raise_for_status()

            # Parse the response for final chunks
            if is_last_chunk:
                message_read = validation.MessageRead(**response.json())
                logging_utility.info(
                    "Final assistant message chunk saved successfully. Message ID: %s",
                    message_read.id
                )
                return message_read
            else:
                logging_utility.info("Non-final assistant message chunk saved successfully.")
                return None  # Non-final chunks return None

        except httpx.HTTPStatusError as e:
            logging_utility.error(
                "HTTP error while saving assistant message chunk: %s (Status: %d)",
                str(e),
                e.response.status_code
            )
            return None  # Failure

        except Exception as e:
            logging_utility.error("Unexpected error while saving assistant message chunk: %s", str(e))
            return None  # Failure

    def submit_tool_output(
            self,
            thread_id: str,
            content: str,
            assistant_id: str,
            tool_id: str,
            role: str = 'tool',
            sender_id: Optional[str] = None,  # Optional sender_id parameter
            meta_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        if meta_data is None:
            meta_data = {}

        message_data = {
            "thread_id": thread_id,
            "content": content,
            "role": role,
            "assistant_id": assistant_id,
            "tool_id": tool_id,
            "meta_data": meta_data
        }

        # Only add sender_id if it's NOT None
        if sender_id is not None:
            message_data["sender_id"] = sender_id

        logging_utility.info("Creating message for thread_id: %s, role: %s", thread_id, role)
        try:

            validated_data = validation.MessageCreate(**message_data)  # Validate data using the Pydantic model

            response = self.client.post("/v1/messages/tools", json=validated_data.dict())
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

