import os

from entities_api.clients.async_to_sync import async_to_sync_stream
from src.api.entities_api.orchestration.workers.base_workers.gpt_oss_base import GptOssBaseWorker

from entities_api.clients.unified_async_client import get_cached_client


class HyperbolicGptOssWorker(GptOssBaseWorker):
    """
    HyperbolicAI Provider for GPT-OSS models.
    Uses standard sync execution.
    """

    def _get_client_instance(self, api_key: str):

        return get_cached_client(
            api_key=api_key, base_url=os.getenv("HYPERBOLIC_BASE_URL"), enable_logging=False
        )

    def _execute_stream_request(self, client, payload: dict):
        # Hyperbolic SDK in this project uses async methods
        async_stream = client.stream_chat_completion(**payload)
        return async_to_sync_stream(async_stream)
