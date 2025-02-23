# entities_api/clients/sandbox_client.py
import httpx
from typing import List
from pydantic import ValidationError
from entities_api.schemas import SandboxCreate, SandboxRead, SandboxUpdate
from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()


class SandboxClientService:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        self.client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"}
        )
        logging_utility.info("SandboxClientService initialized with base_url: %s", self.base_url)

    def create_sandbox(self, **sandbox_data) -> SandboxRead:
        logging_utility.info("Creating sandbox")
        try:
            sandbox = SandboxCreate(**sandbox_data)
            response = self.client.post("/v1/sandboxes", json=sandbox.model_dump())
            response.raise_for_status()
            created_sandbox = response.json()
            validated_sandbox = SandboxRead(**created_sandbox)
            logging_utility.info("Sandbox created with id: %s", validated_sandbox.id)
            return validated_sandbox
        except ValidationError as e:
            logging_utility.error("Validation error during sandbox creation: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error during sandbox creation: %s | Response: %s", str(e), e.response.text)
            raise
        except Exception as e:
            logging_utility.error("Unexpected error during sandbox creation: %s", str(e))
            raise

    def get_sandbox(self, sandbox_id: str) -> SandboxRead:
        logging_utility.info("Retrieving sandbox with id: %s", sandbox_id)
        try:
            response = self.client.get(f"/v1/sandboxes/{sandbox_id}")
            response.raise_for_status()
            sandbox = response.json()
            validated_sandbox = SandboxRead(**sandbox)
            logging_utility.info("Sandbox retrieved successfully")
            return validated_sandbox
        except ValidationError as e:
            logging_utility.error("Validation error during sandbox retrieval: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error during sandbox retrieval: %s | Response: %s", str(e), e.response.text)
            raise
        except Exception as e:
            logging_utility.error("Unexpected error during sandbox retrieval: %s", str(e))
            raise

    def update_sandbox(self, sandbox_id: str, **updates) -> SandboxRead:
        logging_utility.info("Updating sandbox with id: %s", sandbox_id)
        try:
            sandbox_update = SandboxUpdate(**updates)
            response = self.client.put(f"/v1/sandboxes/{sandbox_id}", json=sandbox_update.model_dump(exclude_unset=True))
            response.raise_for_status()
            updated_sandbox = response.json()
            validated_sandbox = SandboxRead(**updated_sandbox)
            logging_utility.info("Sandbox updated successfully")
            return validated_sandbox
        except ValidationError as e:
            logging_utility.error("Validation error during sandbox update: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error during sandbox update: %s | Response: %s", str(e), e.response.text)
            raise
        except Exception as e:
            logging_utility.error("Unexpected error during sandbox update: %s", str(e))
            raise

    def delete_sandbox(self, sandbox_id: str) -> None:
        logging_utility.info("Deleting sandbox with id: %s", sandbox_id)
        try:
            response = self.client.delete(f"/v1/sandboxes/{sandbox_id}")
            response.raise_for_status()
            logging_utility.info("Sandbox deleted successfully")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error during sandbox deletion: %s | Response: %s", str(e), e.response.text)
            raise
        except Exception as e:
            logging_utility.error("Unexpected error during sandbox deletion: %s", str(e))
            raise

    def list_sandboxes_by_user(self, user_id: str) -> List[SandboxRead]:
        logging_utility.info("Listing sandboxes for user_id: %s", user_id)
        try:
            response = self.client.get(f"/v1/users/{user_id}/sandboxes")
            response.raise_for_status()
            sandboxes_data = response.json()
            sandboxes = [SandboxRead(**sandbox) for sandbox in sandboxes_data]
            logging_utility.info("Sandboxes retrieved successfully")
            return sandboxes
        except ValidationError as e:
            logging_utility.error("Validation error during sandboxes retrieval: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error during sandboxes retrieval: %s | Response: %s", str(e), e.response.text)
            raise
        except Exception as e:
            logging_utility.error("Unexpected error during sandboxes retrieval: %s", str(e))
            raise
