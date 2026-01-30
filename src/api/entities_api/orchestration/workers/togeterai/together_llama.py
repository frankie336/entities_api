from src.api.entities_api.orchestration.workers.base_workers.llama_base import \
    LlamaBaseWorker


class TogetherLlamaWorker(LlamaBaseWorker):
    """
    TogetherAI Provider for Llama 3.3.
    Uses standard synchronous streaming.
    """

    def _get_client_instance(self, api_key: str):
        return self._get_together_client(api_key=api_key)
