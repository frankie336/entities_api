from typing import List, Optional, AsyncGenerator

from entities_api.platform_tools.handlers.computer.shell_command_client import (
    run_commands, run_commands_sync)
from src.api.entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()

class ShellCommandInterface:
    def __init__(
        self,
        endpoint: Optional[str] = None,
        thread_id: Optional[str] = None,
        idle_timeout: float = 2.0,
    ):
        self.logging_utility = LoggingUtility()
        self.endpoint = endpoint or "ws://sandbox:8000/ws/computer"
        self.default_thread_id = thread_id or "thread_default_id"
        self.idle_timeout = idle_timeout

    async def run_commands_async_stream(
        self,
        commands: List[str],
        thread_id: Optional[str] = None,
        elevated: bool = False,
    ) -> AsyncGenerator[str, None]:
        """
        Native Async Generator.
        Calls the underlying WebSocket client and yields chunks as they arrive.
        """
        target_room = thread_id or self.default_thread_id
        self.logging_utility.info(f"Executing async stream on room: {target_room}")

        # We assume run_commands is an async generator or returns an awaitable.
        # If run_commands returns a single string, we yield it and finish.
        result = await run_commands(commands, target_room, elevated=elevated)
        yield result

    def run_commands(
        self,
        commands: List[str],
        thread_id: Optional[str] = None,
        elevated: bool = False,
        idle_timeout: Optional[float] = None,
    ) -> str:
        """Keep for backward compatibility with pure sync parts of the app."""
        target_room = thread_id or self.default_thread_id
        return run_commands_sync(commands, target_room, elevated=elevated)

# --- NEW ASYNC ENTRY POINT ---
async def run_shell_commands_async(
    commands: List[str],
    thread_id: Optional[str] = None,
    elevated: bool = False,
    endpoint: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    service = ShellCommandInterface(endpoint=endpoint, thread_id=thread_id)
    async for chunk in service.run_commands_async_stream(
        commands, thread_id=thread_id, elevated=elevated
    ):
        yield chunk
