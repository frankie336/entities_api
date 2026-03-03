from src.api.entities_api.orchestration.mixins import (
    AssistantCacheMixin, ClientFactoryMixin, CodeExecutionMixin,
    ConsumerToolHandlersMixin, ContextMixin, DelegationMixin, FileSearchMixin,
    JsonUtilsMixin, NetworkInventoryMixin, PlatformToolHandlersMixin,
    ScratchpadMixin, ServiceRegistryMixin, ShellExecutionMixin,
    ToolRoutingMixin, WebSearchMixin)


class _ProviderMixins(
    ServiceRegistryMixin,
    ClientFactoryMixin,
    AssistantCacheMixin,
    JsonUtilsMixin,
    ContextMixin,
    DelegationMixin,
    ToolRoutingMixin,
    PlatformToolHandlersMixin,
    ConsumerToolHandlersMixin,
    CodeExecutionMixin,
    ShellExecutionMixin,
    FileSearchMixin,
    WebSearchMixin,
    ScratchpadMixin,
    NetworkInventoryMixin,
):
    """Flat bundle for Provider Mixins."""
