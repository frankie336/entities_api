# entities_api/platform_tools/shell/shell_commands_service.py
import asyncio
from typing import List, Optional
from entities_api.platform_tools.shell.shell_command_client import (
    ShellConnectionManager,
    ShellClientConfig,
    ShellClient
)
from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()


class ShellCommandsService:
    """
    Service class to run shell commands via WebSocket using persistent connections.
    """

    def __init__(self, endpoint: Optional[str] = None, thread_id: Optional[str] = None):
        self.logging_utility = LoggingUtility()
        self.endpoint = endpoint or "ws://localhost:8000/shell"
        self.default_thread_id = thread_id or "thread_cJq1gVLSCpLYI8zzZNRbyc"
        self.manager = ShellConnectionManager()

    def run_commands(self, commands: List[str], thread_id: Optional[str] = None) -> str:
        """
        Synchronous entry point that maintains backward compatibility
        """
        return asyncio.run(self._execute_commands(commands, thread_id))

    async def _execute_commands(self, commands: List[str], thread_id: Optional[str] = None) -> str:
        """Core async execution method with connection pooling"""
        target_thread_id = thread_id or self.default_thread_id

        try:
            client = await self.manager.get_client(
                thread_id=target_thread_id
            )

            self.logging_utility.info(
                "Executing commands on thread %s via %s",
                target_thread_id,
                self.endpoint
            )

            return await client.execute(commands)

        except Exception as e:
            self.logging_utility.error(
                "Command execution failed: %s",
                str(e),
                exc_info=True
            )
            await self.manager.cleanup(self.endpoint, target_thread_id)
            raise

    async def graceful_shutdown(self):
        """Cleanup all connections for this service instance"""
        await self.manager.cleanup_all()


# Maintain backward-compatible function interface
def run_shell_commands(
        commands: List[str],
        thread_id: Optional[str] = None,
        endpoint: Optional[str] = None
) -> str:
    service = ShellCommandsService(endpoint=endpoint)
    return service.run_commands(commands, thread_id)


if __name__ == "__main__":
    # Example usage remains identical
    commands = [
        "echo 'Hello from your personal Linux computer'",
        "ls -la",
        "pwd"
    ]
    output = run_shell_commands(commands)
    print(output)
    logging_utility.info("Collected output:\n%s", output)