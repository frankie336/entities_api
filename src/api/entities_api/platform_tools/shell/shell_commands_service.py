import asyncio
from typing import List, Optional
from entities_api.platform_tools.shell.shell_command_client import run_commands, run_commands_sync
from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()


class ShellCommandsService:
    """
    Service class to run shell commands via WebSocket, aligned with new ShellClient.
    """
    def __init__(self, endpoint: Optional[str] = None, thread_id: Optional[str] = None):
        self.logging_utility = LoggingUtility()
        self.endpoint = endpoint or "ws://sandbox_api:8000/ws/shell"
        self.default_thread_id = thread_id or "thread_cJq1gVLSCpLYI8zzZNRbyc"

    def run_commands(self, commands: List[str], thread_id: Optional[str] = None) -> str:
        """
        Synchronous entry-point for backward compatibility,
        aligned clearly with the new ShellClient.
        """
        target_room = thread_id or self.default_thread_id
        self.logging_utility.info("Executing sync commands on room: %s", target_room)
        return run_commands_sync(commands, target_room)

    async def _execute_commands(self, commands: List[str], thread_id: Optional[str] = None) -> str:
        """
        Async entry-point explicitly aligned with new async ShellClient.
        """
        target_room = thread_id or self.default_thread_id
        self.logging_utility.info("Executing async commands on room: %s", target_room)
        result = await run_commands(commands, target_room)
        return result

    async def graceful_shutdown(self):
        """
        Graceful shutdown no-op (no longer required, workstation specific management).
        """
        self.logging_utility.info("Shutdown called (no clients persist to shutdown).")


# Maintain backward-compatible function interface
def run_shell_commands(
        commands: List[str],
        thread_id: Optional[str] = None,
        endpoint: Optional[str] = None
) -> str:
    service = ShellCommandsService(endpoint=endpoint, thread_id=thread_id)
    return service.run_commands(commands)


# Example & Debugging Usage preserved exactly:
if __name__ == "__main__":
    commands = [
        "echo 'Hello from your personal Linux computer'",
        "ls -la",
        "pwd"
    ]
    output = run_shell_commands(commands)
    print(output)
    logging_utility.info("Collected output:\n%s", output)