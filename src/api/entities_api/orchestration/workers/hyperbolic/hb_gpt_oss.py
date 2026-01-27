import os

from src.api.entities_api.orchestration.workers.base_workers.new_base_gpt_oss_base import \
    GptOssBaseWorker


class HyperbolicGptOssWorker(GptOssBaseWorker):
    """
    HyperbolicAI Provider for GPT-OSS models.
    Uses standard sync execution.
    """

    def _get_client_instance(self, api_key: str):
        # Hyperbolic uses OpenAI-compatible client with a custom Base URL
        return self._get_openai_client(
            base_url=os.getenv("HYPERBOLIC_BASE_URL"), api_key=api_key
        )
