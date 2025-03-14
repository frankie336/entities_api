# entities_api/platform_tools/shell/shell_commands_service.py
from typing import List, Optional
import asyncio
from entities_api.platform_tools.shell.shell_command_client import ShellClient, ShellClientConfig
from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()

class ShellCommandsService:
    """
    Service class to run shell commands via WebSocket and return the full broadcast output.
    """

    def __init__(self, endpoint: Optional[str] = None, thread_id: Optional[str] = None):
        self.logging_utility = LoggingUtility()
        self.endpoint = endpoint or "ws://localhost:8000/shell"
        self.default_thread_id = thread_id or "thread_A42VhvFTiDz3HNV7MzTELq"

    def run_commands(self, commands: List[str], thread_id: Optional[str] = None) -> str:
        """
        Synchronously run shell commands via WebSocket and return the full broadcast output.
        """
        return asyncio.run(self._run_commands(commands, thread_id))

    async def _run_commands(self, commands: List[str], thread_id: Optional[str] = None) -> str:
        config = ShellClientConfig(
            endpoint=self.endpoint,
            thread_id=thread_id or self.default_thread_id
        )
        client = ShellClient(config)
        try:
            self.logging_utility.info("Starting shell session with thread_id: %s", config.thread_id)
            result = await client.run(commands)
            self.logging_utility.info("Shell session completed successfully.")
            return result
        except Exception as e:
            self.logging_utility.error("Error running shell commands: %s", str(e))
            raise

# If needed, you can also expose a simple function interface:
def run_shell_commands(commands: List[str], thread_id: Optional[str] = None) -> str:
    service = ShellCommandsService()
    return service.run_commands(commands, thread_id)

if __name__ == "__main__":
    commands = [
        "echo 'Hello from your personal Linux computer'",
        "ls -la",
        "pwd"
    ]
    output = run_shell_commands(commands)
    print(output)
    logging_utility.info("Collected output:\n%s", output)
