from src.api.entities_api.orchestration.mixins import (
    AssistantCacheMixin, CodeExecutionMixin, ConsumerToolHandlersMixin,
    ContextMixin, DelegationMixin, FileSearchMixin, JsonUtilsMixin,
    NetworkInventoryMixin, PlatformToolHandlersMixin, ScratchpadMixin,
    ServiceRegistryMixin, ShellExecutionMixin, ToolRoutingMixin,
    WebSearchMixin)


class _ProviderMixins(
    AssistantCacheMixin,
    CodeExecutionMixin,
    ConsumerToolHandlersMixin,
    ContextMixin,
    DelegationMixin,
    FileSearchMixin,
    JsonUtilsMixin,
    NetworkInventoryMixin,
    PlatformToolHandlersMixin,
    ScratchpadMixin,
    ServiceRegistryMixin,
    ShellExecutionMixin,
    ToolRoutingMixin,
    WebSearchMixin,
):
    """Flat bundle for Provider Mixins."""
