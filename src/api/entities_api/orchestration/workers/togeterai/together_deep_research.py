import os

from entities_api.clients.unified_async_client import get_cached_client
from entities_api.orchestration.workers.base_workers.deep_research_base import (
    DeepResearchBaseWorker,
)


class TogetherDeepResearchWorker(DeepResearchBaseWorker):
    """
    TogetherAI Provider for GPT-OSS models.
    Uses standard sync execution.
    """

    def _get_client_instance(self, api_key: str):
        """
        Returns an async-ready Hyperbolic client.
        """
        return get_cached_client(
            api_key=os.environ.get("TOGETHER_API_KEY"),
            base_url=os.getenv("TOGETHER_BASE_URL"),
            enable_logging=False,
        )

        # Note: the base class calls client.stream_chat_completion directly.
        # _execute_stream_request is likely not needed anymore, but keeping it
        # for signature compatibility if other parts of your stack call it.

    async def _execute_stream_request(self, client, payload: dict):
        return client.stream_chat_completion(**payload)
