from fastapi import Depends

from src.api.entities_api.dependencies import get_message_cache


class MessageCacheMixin:
    _message_cache = None

    @property
    def message_cache(self):
        if not self._message_cache:
            # Matches the AssistantCache style exactly
            self._message_cache = Depends(get_message_cache)()
        return self._message_cache
