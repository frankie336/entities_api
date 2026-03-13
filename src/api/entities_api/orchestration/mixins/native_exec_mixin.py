# src/api/entities_api/orchestration/mixins/native_exec_mixin.py
from __future__ import annotations

from src.api.entities_api.services.native_execution_service import \
    NativeExecutionService


class NativeExecMixin:
    """
    Provides a lazy singleton NativeExecutionService instance.

    Mix this in to any class that needs NativeExecutionService without
    adding it to the MRO or requiring __init__ cooperation.

    Usage:
        class MyMixin(NativeExecMixin):
            async def do_something(self):
                await self._native_exec.submit_tool_output(...)

    Notes:
        - Single leading underscore avoids Python name-mangling, which
          would make the attribute invisible to subclasses.
        - getattr guard means this works even when the concrete subclass
          does not call super().__init__() through the full MRO
          (e.g. TogetherQwenWorker and similar provider workers).
        - The instance is created once per mixin instance and reused,
          so Redis / DB connections are shared across calls within a
          single request lifecycle.
    """

    @property
    def _native_exec(self) -> NativeExecutionService:
        if getattr(self, "_native_exec_svc", None) is None:
            self._native_exec_svc = NativeExecutionService()
        return self._native_exec_svc
