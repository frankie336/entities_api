from src.api.entities_api.orchestration.mixins import (
    AssistantCacheMixin,
    CodeExecutionMixin,
    ConsumerToolHandlersMixin,
    ConversationContextMixin,
    FileSearchMixin,
    JsonUtilsMixin,
    PlatformToolHandlersMixin,
    ShellExecutionMixin,
    ToolRoutingMixin,
)


class _ProviderMixins(
    AssistantCacheMixin,
    JsonUtilsMixin,
    ConversationContextMixin,
    ToolRoutingMixin,
    PlatformToolHandlersMixin,
    ConsumerToolHandlersMixin,
    CodeExecutionMixin,
    ShellExecutionMixin,
    FileSearchMixin,
):
    """Flat bundle for Provider Mixins."""
