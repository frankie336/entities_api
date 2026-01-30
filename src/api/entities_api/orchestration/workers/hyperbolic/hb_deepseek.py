import os

from src.api.entities_api.orchestration.workers.base_workers.deepseek_base import DeepSeekBaseWorker


class HyperbolicDs1(DeepSeekBaseWorker):
    """Hyperbolic-specific implementation of DeepSeek."""

    def _get_client_instance(self, api_key: str):
        # Hyperbolic uses OpenAI-compatible client with a custom Base URL
        return self._get_openai_client(base_url=os.getenv("HYPERBOLIC_BASE_URL"), api_key=api_key)
