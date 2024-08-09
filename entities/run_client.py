import httpx
import time
from typing import List, Dict, Any, Optional
from pydantic import ValidationError
from services.identifier_service import IdentifierService
from services.loggin_service import LoggingUtility
from api.v1.schemas import Run, RunStatusUpdate  # Import the relevant Pydantic models

# Initialize logging utility
logging_utility = LoggingUtility()

class RunService:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        self.client = httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {api_key}"})
        logging_utility.info("RunService initialized with base_url: %s", self.base_url)

    def create_run(self, assistant_id: str, thread_id: str, instructions: Optional[str] = "",
                   meta_data: Optional[Dict[str, Any]] = {}) -> Dict[str, Any]:
        run_data = {
            "id": IdentifierService.generate_run_id(),
            "assistant_id": assistant_id,
            "thread_id": thread_id,
            "instructions": instructions,
            "meta_data": meta_data,
            "cancelled_at": None,
            "completed_at": None,
            "created_at": int(time.time()),
            "expires_at": int(time.time()) + 3600,  # Set to 1 hour later
            "failed_at": None,
            "incomplete_details": None,
            "last_error": None,
            "max_completion_tokens": 1000,
            "max_prompt_tokens": 500,
            "model": "gpt-4",
            "object": "run",
            "parallel_tool_calls": False,
            "required_action": None,
            "response_format": "text",
            "started_at": None,
            "status": "pending",
            "tool_choice": "none",
            "tools": [],
            "truncation_strategy": {},
            "usage": None,
            "temperature": 0.7,
            "top_p": 0.9,
            "tool_resources": {}
        }
        logging_utility.info("Creating run for assistant_id: %s, thread_id: %s", assistant_id, thread_id)
        logging_utility.debug("Run data: %s", run_data)
        try:
            validated_data = Run(**run_data)  # Validate data using Pydantic model
            response = self.client.post("/v1/runs", json=validated_data.dict())
            response.raise_for_status()
            created_run = response.json()
            logging_utility.info("Run created successfully with id: %s", created_run.get('id'))
            return created_run
        except ValidationError as e:
            logging_utility.error("Validation error: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while creating run: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while creating run: %s", str(e))
            raise

    def retrieve_run(self, run_id: str) -> Run:
        logging_utility.info("Retrieving run with id: %s", run_id)
        try:
            response = self.client.get(f"/v1/runs/{run_id}")
            response.raise_for_status()
            run = response.json()
            validated_run = Run(**run)  # Validate data using Pydantic model
            logging_utility.info("Run retrieved successfully")
            return validated_run
        except ValidationError as e:
            logging_utility.error("Validation error: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while retrieving run: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while retrieving run: %s", str(e))
            raise

    def update_run_status(self, run_id: str, new_status: str) -> Run:
        logging_utility.info("Updating run status for run_id: %s to %s", run_id, new_status)
        update_data = {
            "status": new_status
        }
        try:
            validated_data = RunStatusUpdate(**update_data)  # Validate data using Pydantic model
            response = self.client.put(f"/v1/runs/{run_id}/status", json=validated_data.dict())
            response.raise_for_status()
            updated_run = response.json()
            validated_run = Run(**updated_run)  # Validate data using Pydantic model
            logging_utility.info("Run status updated successfully")
            return validated_run
        except ValidationError as e:
            logging_utility.error("Validation error: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while updating run status: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while updating run status: %s", str(e))
            raise

    def list_runs(self, limit: int = 20, order: str = "asc") -> List[Run]:
        logging_utility.info("Listing runs with limit: %d, order: %s", limit, order)
        params = {
            "limit": limit,
            "order": order
        }
        try:
            response = self.client.get("/v1/runs", params=params)
            response.raise_for_status()
            runs = response.json()
            validated_runs = [Run(**run) for run in runs]  # Validate data using Pydantic model
            logging_utility.info("Retrieved %d runs", len(validated_runs))
            return validated_runs
        except ValidationError as e:
            logging_utility.error("Validation error: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while listing runs: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while listing runs: %s", str(e))
            raise

    def delete_run(self, run_id: str) -> Dict[str, Any]:
        logging_utility.info("Deleting run with id: %s", run_id)
        try:
            response = self.client.delete(f"/v1/runs/{run_id}")
            response.raise_for_status()
            result = response.json()
            logging_utility.info("Run deleted successfully")
            return result
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while deleting run: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while deleting run: %s", str(e))
            raise

    def generate(self, run_id: str, model: str, prompt: str, stream: bool = False) -> Dict[str, Any]:
        logging_utility.info("Generating content for run_id: %s, model: %s", run_id, model)
        try:
            run = self.retrieve_run(run_id)
            response = self.client.post(
                "/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": stream,
                    "context": run.meta_data.get("context", []),
                    "temperature": run.temperature,
                    "top_p": run.top_p
                }
            )
            response.raise_for_status()
            result = response.json()
            logging_utility.info("Content generated successfully")
            return result
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while generating content: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while generating content: %s", str(e))
            raise

    def chat(self, run_id: str, model: str, messages: List[Dict[str, Any]], stream: bool = False) -> Dict[str, Any]:
        logging_utility.info("Chatting for run_id: %s, model: %s", run_id, model)
        try:
            run = self.retrieve_run(run_id)
            response = self.client.post(
                "/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": stream,
                    "context": run.meta_data.get("context", []),
                    "temperature": run.temperature,
                    "top_p": run.top_p
                }
            )
            response.raise_for_status()
            result = response.json()
            logging_utility.info("Chat completed successfully")
            return result
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred during chat: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred during chat: %s", str(e))
            raise
