from src.api.entities_api.orchestration.workers.base_workers.deepseek_base import (
    DeepSeekBaseWorker,
)


class TogetherDs1(DeepSeekBaseWorker):
    """TogetherAI-specific implementation of DeepSeek."""

    def _get_client_instance(self, api_key: str):
        # Together uses its native client (or OpenAI compat)
        # Assuming _get_together_client is defined in your _ProviderMixins or you import the lib
        return self._get_together_client(api_key=api_key)
