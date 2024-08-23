import httpx
import time
from typing import List, Dict, Any, Optional
from pydantic import ValidationError
from entities_api.services.identifier_service import IdentifierService
from entities_api.services.loggin_service import LoggingUtility
from entities_api.schemas import Run, RunStatusUpdate

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
            "status": "queued",
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
            validated_data = Run(**run_data)
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
            validated_run = Run(**run)
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

    def start_run(self, run_id: str) -> Run:
        try:
            return self.update_run_status(run_id, "in_progress")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 409:
                logging_utility.warning("Another run is already in progress for this thread")
                raise ValueError("Another run is already in progress for this thread")
            raise

    def fail_run(self, run_id: str, error_message: str) -> Run:
        run = self.update_run_status(run_id, "failed")
        self.update_run_details(run_id, {"last_error": error_message})
        return run

    def cancel_run(self, run_id: str) -> Run:
        return self.update_run_status(run_id, "cancelled")

    def expire_run(self, run_id: str) -> Run:
        return self.update_run_status(run_id, "expired")

    def update_run_status(self, run_id: str, new_status: str) -> Run:
        logging_utility.info("Updating run status for run_id: %s to %s", run_id, new_status)
        if new_status not in ["queued", "in_progress", "completed", "failed", "cancelled", "expired"]:
            raise ValueError(f"Invalid status: {new_status}")

        current_time = int(time.time())
        update_data = {"status": new_status, "last_activity_at": current_time}
        try:
            validated_data = RunStatusUpdate(**update_data)
            response = self.client.put(f"/v1/runs/{run_id}/status", json=validated_data.dict())
            response.raise_for_status()
            updated_run = response.json()
            validated_run = Run(**updated_run)
            logging_utility.info("Run status updated successfully")
            return validated_run
        except ValidationError as e:
            logging_utility.error("Validation error: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 409 and new_status == "in_progress":
                logging_utility.warning("Another run is already in progress for this thread")
                raise ValueError("Another run is already in progress for this thread")
            logging_utility.error("HTTP error occurred while updating run status: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while updating run status: %s", str(e))
            raise

    def update_run_activity(self, run_id: str) -> Run:
        logging_utility.info("Updating run activity for run_id: %s", run_id)
        current_time = int(time.time())
        update_data = {"last_activity_at": current_time}
        try:
            response = self.client.patch(f"/v1/runs/{run_id}", json=update_data)
            response.raise_for_status()
            updated_run = response.json()
            validated_run = Run(**updated_run)
            logging_utility.info("Run activity updated successfully")
            return validated_run
        except ValidationError as e:
            logging_utility.error("Validation error: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while updating run activity: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while updating run activity: %s", str(e))
            raise

    def update_run_details(self, run_id: str, details: Dict[str, Any]) -> Run:
        logging_utility.info("Updating run details for run_id: %s", run_id)
        try:
            response = self.client.patch(f"/v1/runs/{run_id}", json=details)
            response.raise_for_status()
            updated_run = response.json()
            validated_run = Run(**updated_run)
            logging_utility.info("Run details updated successfully")
            return validated_run
        except ValidationError as e:
            logging_utility.error("Validation error: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while updating run details: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while updating run details: %s", str(e))
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
            validated_runs = [Run(**run) for run in runs]
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
            if run.status != "in_progress":
                self.start_run(run_id)

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

            self.complete_run(run_id)
            logging_utility.info("Content generated successfully")
            return result
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while generating content: %s", str(e))
            self.fail_run(run_id, str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while generating content: %s", str(e))
            self.fail_run(run_id, str(e))
            raise

    def chat(self, run_id: str, model: str, messages: List[Dict[str, Any]], stream: bool = False) -> Dict[str, Any]:
        logging_utility.info("Chatting for run_id: %s, model: %s", run_id, model)
        try:
            run = self.retrieve_run(run_id)
            if run.status != "in_progress":
                self.start_run(run_id)

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

            self.complete_run(run_id)
            logging_utility.info("Chat completed successfully")
            return result
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred during chat: %s", str(e))
            self.fail_run(run_id, str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred during chat: %s", str(e))
            self.fail_run(run_id, str(e))
            raise