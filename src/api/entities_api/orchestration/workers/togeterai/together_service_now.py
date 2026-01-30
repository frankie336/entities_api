from src.api.entities_api.orchestration.workers.base_workers.service_now_base import (
    ServiceNowBaseWorker,
)


class TogetherServiceNowWorker(ServiceNowBaseWorker):
    """TogetherAI-specific implementation of ServiceNowBaseWorker."""

    def _get_client_instance(self, api_key: str):
        # Together uses its native client (or OpenAI compat)
        return self._get_together_client(api_key=api_key)

    def _execute_stream_request(self, client, payload: dict):
        """
        Executes the synchronous stream request using the Together/OpenAI client.
        Required by OrchestratorCore.
        """
        # Ensure payload has 'stream': True if required by the client,
        # though usually OrchestratorCore sets this in the payload.
        return client.chat.completions.create(**payload)
