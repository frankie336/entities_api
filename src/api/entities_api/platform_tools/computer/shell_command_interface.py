import asyncio
from typing import List, Optional
from entities_api.platform_tools.computer.shell_command_client import run_commands, run_commands_sync
from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()


class ShellCommandInterface:
    """
    Service class to run computer commands via WebSocket, aligned with new ShellClient.
    """
    def __init__(self, endpoint: Optional[str] = None, thread_id: Optional[str] = None, idle_timeout: float = 2.0):
        self.logging_utility = LoggingUtility()
        self.endpoint = endpoint or "ws://sandbox_api:8000/ws/computer"
        self.default_thread_id = thread_id or "thread_cJq1gVLSCpLYI8zzZNRbyc"
        self.idle_timeout = idle_timeout  # Added idle timeout support

    def run_commands(self, commands: List[str], thread_id: Optional[str] = None, elevated: bool = False, idle_timeout: Optional[float] = None) -> str:
        """
        Synchronous entry-point for backward compatibility,
        aligned clearly with the new ShellClient.
        """
        target_room = thread_id or self.default_thread_id
        timeout = idle_timeout if idle_timeout is not None else self.idle_timeout
        self.logging_utility.info(f"Executing sync commands on room: {target_room} with elevation={elevated} and idle_timeout={timeout}")
        return run_commands_sync(commands, target_room, elevated=elevated, idle_timeout=timeout)

    async def _execute_commands(self, commands: List[str], thread_id: Optional[str] = None, elevation: bool = False, idle_timeout: Optional[float] = None) -> str:
        """
        Async entry-point explicitly aligned with new async ShellClient.
        """
        target_room = thread_id or self.default_thread_id
        timeout = idle_timeout if idle_timeout is not None else self.idle_timeout
        self.logging_utility.info(f"Executing async commands on room: {target_room} with elevation={elevation} and idle_timeout={timeout}")
        result = await run_commands(commands, target_room, elevated=elevation, idle_timeout=timeout)
        return result

    async def graceful_shutdown(self):
        """
        Graceful shutdown no-op (no longer required, workstation-specific management).
        """
        self.logging_utility.info("Shutdown called (no clients persist to shutdown).")


# Maintain backward-compatible function interface
def run_shell_commands(
        commands: List[str],
        thread_id: Optional[str] = None,
        elevated: bool = False,
        endpoint: Optional[str] = None,
        idle_timeout: Optional[float] = None
) -> str:
    service = ShellCommandInterface(endpoint=endpoint, thread_id=thread_id, idle_timeout=idle_timeout or 2.0)
    return service.run_commands(commands, thread_id=thread_id, elevated=elevated, idle_timeout=idle_timeout)


# Example & Debugging Usage preserved exactly:
if __name__ == "__main__":
    commands = [
        "echo 'Hello from your personal Linux computer'",
        "ls -la",
        "pwd"
    ]
    output = run_shell_commands(commands, elevated=True, idle_timeout=5.0)
    print(output)
    logging_utility.info("Collected output:\n%s", output)