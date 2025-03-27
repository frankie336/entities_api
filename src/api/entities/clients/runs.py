import httpx
import time
from typing import List, Dict, Any, Optional
from pydantic import ValidationError
from entities.services.logging_service import LoggingUtility
from entities_common import ValidationInterface, UtilsInterface

validation = ValidationInterface()

# Initialize logging utility
logging_utility = LoggingUtility()


class RunsClient:
    def __init__(self, base_url="http://localhost:9000/", api_key=None):
        self.base_url = base_url
        self.api_key = api_key
        self.client = httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {api_key}"})
        logging_utility.info("RunsClient initialized with base_url: %s", self.base_url)

    def create_run(self, assistant_id: str, thread_id: str, instructions: Optional[str] = "",
                   meta_data: Optional[Dict[str, Any]] = {}) -> validation.Run:  # Return type is now RunReadDetailed
        run_data = validation.Run(  # Use Pydantic model for creation
            id=UtilsInterface.IdentifierService.generate_run_id(),
            assistant_id=assistant_id,
            thread_id=thread_id,
            instructions=instructions,
            meta_data=meta_data,
            cancelled_at=None,
            completed_at=None,
            created_at=int(time.time()),
            expires_at=int(time.time()) + 3600,  # Set to 1 hour later
            failed_at=None,
            incomplete_details=None,
            last_error=None,
            max_completion_tokens=1000,
            max_prompt_tokens=500,
            model="llama3.1",
            object="run",
            parallel_tool_calls=False,
            required_action=None,
            response_format="text",
            started_at=None,
            status="pending",
            tool_choice="none",
            tools=[],
            truncation_strategy={},
            usage=None,
            temperature=0.7,
            top_p=0.9,
            tool_resources={}
        )

        logging_utility.info("Creating run for assistant_id: %s, thread_id: %s", assistant_id, thread_id)
        logging_utility.debug("Run data: %s", run_data.dict())

        try:
            # Send the validated data to the API
            response = self.client.post("/v1/runs", json=run_data.dict())
            response.raise_for_status()
            created_run_data = response.json()

            # Validate the response data with the Pydantic model
            validated_run = validation.Run(**created_run_data)
            logging_utility.info("Run created successfully with id: %s", validated_run.id)

            # Return the Pydantic model instead of the raw dictionary
            return validated_run

        except ValidationError as e:
            logging_utility.error("Validation error: %s", e.json())
            raise ValueError(f"Validation error: {e}")
        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while creating run: %s", str(e))
            raise
        except Exception as e:
            logging_utility.error("An error occurred while creating run: %s", str(e))
            raise

    def retrieve_run(self, run_id: str) -> validation.RunReadDetailed:
        """
        Retrieve a run by ID and return the Pydantic object.
        The Pydantic object has methods like .dict() and .json().
        """
        logging_utility.info("Retrieving run with id: %s", run_id)

        try:
            # Making the HTTP GET request to the runs endpoint
            response = self.client.get(f"/routers/runs/{run_id}")
            response.raise_for_status()

            # Parsing and validating the response JSON into a Pydantic RunReadDetailed model
            run_data = response.json()
            validated_run = validation.RunReadDetailed(**run_data)  # Validate data using Pydantic model

            logging_utility.info("Run with id %s retrieved and validated successfully", run_id)
            return validated_run

        except ValidationError as e:
            logging_utility.error("Validation error: %s", e.json())
            raise ValueError(f"Data validation failed: {e}")

        except httpx.HTTPStatusError as e:
            logging_utility.error("HTTP error occurred while retrieving run: %s", str(e))
            raise

        except Exception as e:
            logging_utility.error("An unexpected error occurred while retrieving run: %s", str(e))
            raise

    def update_run_status(self, run_id: str, new_status: str) -> validation.Run:
        logging_utility.info("Updating run status for run_id: %s to %s", run_id, new_status)

        # Prepare the update data for validation
        update_data = {
            "status": new_status
        }

        try:
            # Validate the update data using your RunStatusUpdate model
            validated_data = validation.RunStatusUpdate(**update_data)

            # Send the validated data to the backend via a PUT request
            response = self.client.put(f"/v1/runs/{run_id}/status", json=validated_data.dict())
            response.raise_for_status()

            # Parse the updated run from the response JSON
            updated_run = response.json()
            validated_run = validation.Run(**updated_run)  # Validate/parse using your Run Pydantic model

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

    def list_runs(self, limit: int = 20, order: str = "asc") -> List[validation.Run]:
        logging_utility.info("Listing runs with limit: %d, order: %s", limit, order)
        params = {
            "limit": limit,
            "order": order
        }
        try:
            response = self.client.get("/routers/runs", params=params)
            response.raise_for_status()
            runs = response.json()
            validated_runs = [validation.Run(**run) for run in runs]  # Validate data using Pydantic model
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

    def cancel_run(self, run_id: str) -> Dict[str, Any]:
        logging_utility.info(f"Cancelling run with id: {run_id}")
        try:
            response = self.client.post(f"/v1/runs/{run_id}/cancel")
            response.raise_for_status()
            result = response.json()
            logging_utility.info(f"Run {run_id} cancelled successfully")
            return result
        except httpx.HTTPStatusError as e:
            logging_utility.error(f"HTTP error occurred while cancelling run {run_id}: {str(e)}")
            raise
        except Exception as e:
            logging_utility.error(f"An error occurred while cancelling run {run_id}: {str(e)}")
            raise
