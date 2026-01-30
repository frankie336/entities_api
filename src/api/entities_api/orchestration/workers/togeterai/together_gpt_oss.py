from src.api.entities_api.orchestration.workers.base_workers.base_gpt_oss_base import \
    GptOssBaseWorker


class TogetherGptOssWorker(GptOssBaseWorker):
    """
    TogetherAI Provider for GPT-OSS models.
    Uses standard sync execution.
    """

    def _get_client_instance(self, api_key: str):
        return self._get_together_client(api_key=api_key)

    def _execute_stream_request(self, client, payload: dict):
        return client.chat.completions.create(**payload)
