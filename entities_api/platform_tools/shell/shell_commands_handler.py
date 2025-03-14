from typing import List, Optional
import asyncio
from entities_api.platform_tools.shell.shell_command_client import ShellClient, ShellClientConfig
from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()

def run_shell_commands(commands: List[str], thread_id: Optional[str] = None) -> str:
    """
    Synchronously run shell commands on the remote shell via WebSockets and return the full broadcast output.
    """
    return asyncio.run(_run_shell_commands(commands, thread_id))

async def _run_shell_commands(commands: List[str], thread_id: Optional[str] = None) -> str:
    config = ShellClientConfig(
        endpoint="ws://localhost:8000/shell",
        thread_id=thread_id or "thread_2ycHHuZk0v3xPei768a9c6"
    )
    client = ShellClient(config)
    try:
        logging_utility.info("Starting shell session with thread_id: %s", config.thread_id)
        result = await client.run(commands)
        logging_utility.info("Shell session completed successfully.")
        return result
    except Exception as e:
        logging_utility.error("Error running shell commands: %s", str(e))
        raise

if __name__ == "__main__":
    commands = [
        "echo 'Hello from your personal Linux computer'",
        "ls -la",
        "pwd"
    ]
    output = run_shell_commands(commands)
    print(output)
    logging_utility.info("Collected output:\n%s", output)
