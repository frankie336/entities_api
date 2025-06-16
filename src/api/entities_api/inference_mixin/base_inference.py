from __future__ import annotations

import os
from typing import TYPE_CHECKING

import httpx
from openai import OpenAI
from projectdavid import Entity
from together import Together

from entities_api.inference_mixin.mixins.client_factory_mixin import \
    ClientFactoryMixin
from entities_api.inference_mixin.mixins.code_execution_mixin import \
    CodeExecutionMixin
from entities_api.inference_mixin.mixins.consumer_tool_handlers_mixin import \
    ConsumerToolHandlersMixin
from entities_api.inference_mixin.mixins.conversation_context_mixin import \
    ConversationContextMixin
from entities_api.inference_mixin.mixins.json_utils_mixin import JsonUtilsMixin
from entities_api.inference_mixin.mixins.platform_tool_handlers_mixin import \
    PlatformToolHandlersMixin
from entities_api.inference_mixin.mixins.service_registry_mixin import \
    ServiceRegistryMixin
from entities_api.inference_mixin.mixins.shell_execution_mixin import \
    ShellExecutionMixin
from entities_api.inference_mixin.mixins.streaming_mixin import StreamingMixin
from entities_api.inference_mixin.mixins.tool_routing_mixin import \
    ToolRoutingMixin

if TYPE_CHECKING:
    from redis import Redis

    from entities_api.services.cached_assistant import AssistantCache


class BaseInference(
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
):
    """Central orchestrator that all provider-specific inference classes inherit."""

    def __init__(self, *, redis: "Redis", assistant_cache: "AssistantCache", **kw):
        super().__init__()
        self.redis = redis
        self.assistant_cache = assistant_cache

        # ── Default external clients (constructed once per instance) ─────────
        self.openai_client = OpenAI(
            api_key=os.getenv("TOGETHER_API_KEY"),
            base_url=os.getenv("BASE_URL"),
            timeout=httpx.Timeout(30, read=30),
        )
        self.together_client = Together(api_key=os.getenv("TOGETHER_API_KEY"))
        self.project_david_client = Entity(
            api_key=os.getenv("ADMIN_API_KEY"),
            base_url=os.getenv("BASE_URL"),
        )

        # Placeholder for any additional kwargs that future providers might use
        # without forcing a signature change.
        self._extra_kwargs = kw

        # Initialize the lazy-load service cache
        self._services = {}
