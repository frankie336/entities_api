import os

from entities_api.clients.async_to_sync import async_to_sync_stream
from src.api.entities_api.orchestration.workers.base_workers.service_now_base import (
    ServiceNowBaseWorker,
)


class TogetherServiceNowWorker(ServiceNowBaseWorker):
    """TogetherAI-specific implementation of ServiceNowBaseWorker."""

    def _get_client_instance(self, api_key: str):
        return self._get_unified_client(
            base_url=os.getenv("TOGETHER_BASE_URL"), api_key=api_key
        )

    def _execute_stream_request(self, client, payload: dict):
        # Hyperbolic SDK in this project uses async methods
        async_stream = client.stream_chat_completion(**payload)
        return async_to_sync_stream(async_stream)
