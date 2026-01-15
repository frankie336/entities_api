from fastapi import Depends

from src.api.entities_api.dependencies import get_assistant_cache


class AssistantCacheMixin:
    _assistant_cache = None

    @property
    def assistant_cache(self):
        if not self._assistant_cache:
            self._assistant_cache = Depends(get_assistant_cache)()
        return self._assistant_cache
