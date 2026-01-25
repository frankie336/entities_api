import os

from src.api.entities_api.orchestration.workers.base_workers.gpt_oss_base import \
    GptOssBaseWorker
from src.api.entities_api.utils.async_to_sync import async_to_sync_stream


class HyperbolicGptOssWorker(GptOssBaseWorker):
    """
    Hyperbolic Provider for GPT-OSS models.
    Uses async_to_sync bridge.
    """

    def _get_client_instance(self, api_key: str):
        if isinstance(self.model_name, str) and self.model_name.startswith(
            "hyperbolic/"
        ):
            self.model_name = self.model_name.replace("hyperbolic/", "")

        return self._get_hyperbolic_client(
            api_key=api_key, base_url=os.getenv("HYPERBOLIC_BASE_URL")
        )

    def _execute_stream_request(self, client, payload: dict):
        async_stream = client.stream_chat_completion(**payload)
        return async_to_sync_stream(async_stream)
