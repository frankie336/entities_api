from src.api.entities_api.orchestration.workers.base_workers.deepseek_base import (
    DeepSeekBaseWorker,
)


class TogetherDs1(DeepSeekBaseWorker):
    """TogetherAI-specific implementation of DeepSeek."""

    def _get_client_instance(self, api_key: str):
        return self._get_together_client(api_key=api_key)

    def _execute_stream_request(self, client, payload: dict):
        return client.chat.completions.create(**payload)
