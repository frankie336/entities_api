import os

from entities_api.orchestration.workers.base_workers.llama_base import LlamaBaseWorker
from entities_api.utils.async_to_sync import async_to_sync_stream


class HyperbolicLlamaWorker(LlamaBaseWorker):
    """
    Hyperbolic Provider for Llama 3.3.
    Uses async_to_sync bridge for client streaming.
    """

    def _get_client_instance(self, api_key: str):
        return self._get_hyperbolic_client(
            api_key=api_key, base_url=os.getenv("HYPERBOLIC_BASE_URL")
        )

    def _execute_stream_request(self, client, payload: dict):
        # Hyperbolic SDK in this project uses async methods
        async_stream = client.stream_chat_completion(**payload)
        return async_to_sync_stream(async_stream)
