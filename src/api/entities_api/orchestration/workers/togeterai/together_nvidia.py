from src.api.entities_api.orchestration.workers.base_workers.nvidia_base import NvidiaBaseWorker


class TogetherNvidiaWorker(NvidiaBaseWorker):
    """TogetherAI-specific implementation of Nvidia."""

    def _get_client_instance(self, api_key: str):
        # Together uses its native client (or OpenAI compat)
        return self._get_together_client(api_key=api_key)
