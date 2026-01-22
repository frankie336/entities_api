"""
orchestrator_core.py
────────────────────
The ultra-thin root class.

• Glues together every functional mix-in in the correct MRO order
• Carries only a few shared state fields
• Leaves `stream` + `process_conversation` abstract so each provider
  (Hyperbolic, OpenAI, Together, …) can implement its own wire-format.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generator, Optional

from src.api.entities_api.orchestration.mixins.client_factory_mixin import (
    ClientFactoryMixin,
)
from src.api.entities_api.orchestration.mixins.code_execution_mixin import (
    CodeExecutionMixin,
)
from src.api.entities_api.orchestration.mixins.consumer_tool_handlers_mixin import (
    ConsumerToolHandlersMixin,
)
from src.api.entities_api.orchestration.mixins.conversation_context_mixin import (
    ConversationContextMixin,
)
from src.api.entities_api.orchestration.mixins.json_utils_mixin import JsonUtilsMixin
from src.api.entities_api.orchestration.mixins.platform_tool_handlers_mixin import (
    PlatformToolHandlersMixin,
)
from src.api.entities_api.orchestration.mixins.service_registry_mixin import (
    ServiceRegistryMixin,
)
from src.api.entities_api.orchestration.mixins.shell_execution_mixin import (
    ShellExecutionMixin,
)
from src.api.entities_api.orchestration.mixins.streaming_mixin import StreamingMixin
from src.api.entities_api.orchestration.mixins.tool_routing_mixin import (
    ToolRoutingMixin,
)


class OrchestratorCore(
    ClientFactoryMixin,
    ServiceRegistryMixin,
    JsonUtilsMixin,
    ConversationContextMixin,
    ToolRoutingMixin,
    PlatformToolHandlersMixin,
    ConsumerToolHandlersMixin,
    StreamingMixin,
    CodeExecutionMixin,
    ShellExecutionMixin,
    ABC,
):
    """
    All behaviour resides in the mix-ins.
    Concrete provider classes only need to implement:

        • stream()
        • process_conversation()

    Everything else (tool routing, history, JSON hygiene, …) is inherited.
    """

    tool_response: Optional[bool] = None
    function_call: Optional[dict] = None
    _cancelled: bool = False
    code_mode: bool = False

    @abstractmethod
    def stream(
        self,
        thread_id: str,
        message_id: str,
        run_id: str,
        assistant_id: str,
        model: Any,
        *,
        stream_reasoning: bool = True,
        api_key: Optional[str] = None,
    ) -> Generator[str, None, None]:
        """
        Must open a streaming connection to the underlying LLM provider,
        parse deltas into the mix-in JSON chunk format and `yield` them.

        Every provider has its own SDK quirks – that's why we leave this
        abstract.
        """

    @abstractmethod
    def process_conversation(
        self,
        thread_id: str,
        message_id: str,
        run_id: str,
        assistant_id: str,
        model: Any,
        *,
        stream_reasoning: bool = False,
        api_key: Optional[str] = None,
    ) -> Generator[str, None, None]:
        """
        Typical pattern inside an implementation:

            for chunk in self.stream(...):
                yield chunk

            for chunk in self.process_tool_calls(...):
                yield chunk

            # optional: another self.stream(...) round-trip if a tool
            #           produced new user-visible content
        """
