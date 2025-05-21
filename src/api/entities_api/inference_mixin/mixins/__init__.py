# mixins/__init__.py
# -------------------------------------------------------------------------
# One-stop import surface for all mix-ins
# -------------------------------------------------------------------------

from .assistant_cache_mixin import AssistantCacheMixin
from .client_factory_mixin import ClientFactoryMixin
from .code_execution_mixin import CodeExecutionMixin
from .consumer_tool_handlers_mixin import ConsumerToolHandlersMixin
from .conversation_context_mixin import ConversationContextMixin
from .json_utils_mixin import JsonUtilsMixin
from .platform_tool_handlers_mixin import PlatformToolHandlersMixin
from .service_registry_mixin import ServiceRegistryMixin
from .shell_execution_mixin import ShellExecutionMixin
from .streaming_mixin import StreamingMixin
from .tool_routing_mixin import ToolRoutingMixin

__all__ = [
    # Core plumbing
    "ClientFactoryMixin",
    "ServiceRegistryMixin",
    "JsonUtilsMixin",
    "ConversationContextMixin",
    "AssistantCacheMixin",
    # Tool routing & handlers
    "ToolRoutingMixin",
    "PlatformToolHandlersMixin",
    "ConsumerToolHandlersMixin",
    # Streaming / execution
    "StreamingMixin",
    "CodeExecutionMixin",
    "ShellExecutionMixin",
]
