import asyncio
import json
from typing import Optional, List

import websockets

from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()

# A simple configuration class for the client.
class ShellClientConfig:
    def __init__(self,
                 endpoint: str = "ws://sandbox:8000/shell",
                 thread_id: Optional[str] = None,
                 timeout: int = 5):
        self.endpoint = endpoint
        self.thread_id = thread_id
        self.timeout = timeout  # Timeout for inactivity (no longer used)

# Main client class that uses the websockets library.
class ShellClient:
    def __init__(self, config: Optional[ShellClientConfig] = None):
        self.config = config or ShellClientConfig()
        self.ws = None

    async def connect(self):
        """
        Connect to the WebSocket server.
        Here we encode authentication info in query parameters instead of using extra_headers.
        """
        # Build query parameters for authentication.
        query = f"?thread_id={self.config.thread_id}&user_id=system"
        endpoint_with_query = f"{self.config.endpoint}{query}"
        logging_utility.info("Connecting to %s", endpoint_with_query)
        self.ws = await websockets.connect(endpoint_with_query)
        logging_utility.info("WebSocket connected.")

    async def join_room(self):
        """
        Send a join_room action to the server so that it creates the PTY session and adds the client to the correct room.
        """
        if not self.ws:
            raise Exception("WebSocket is not connected!")
        join_message = json.dumps({
            "action": "join_room",
            "room": self.config.thread_id
        })
        logging_utility.info("Joining room: %s", self.config.thread_id)
        await self.ws.send(join_message)

    async def send_command(self, command: str):
        """
        Send a shell command to the server.
        The command is packaged as JSON with an action of 'shell_command'.
        """
        if not self.ws:
            raise Exception("WebSocket is not connected!")
        message = json.dumps({
            "action": "shell_command",
            "command": command,
            "thread_id": self.config.thread_id  # Including thread_id as additional info if needed.
        })
        logging_utility.info("Sending command: %s", command)
        await self.ws.send(message)

    async def run(self, commands: List[str], thread_id: Optional[str] = None) -> str:
        """
        Connect to the server, join the room, send the given list of commands,
        and then gather broadcasted shell output from the server into a single string,
        which is returned after the session is complete.
        """
        # Update configuration if a new thread ID is provided.
        self.config.thread_id = thread_id or self.config.thread_id
        logging_utility.info("Starting session with thread ID: %s", self.config.thread_id)

        await self.connect()
        await self.join_room()

        # Send all commands sequentially.
        for command in commands:
            await self.send_command(command)

        # Gather broadcast messages from the server without a timeout.
        broadcast_buffer = ""
        try:
            while True:
                message = await self.ws.recv()  # Wait indefinitely for a message.
                try:
                    data = json.loads(message)
                    logging_utility.info("Received JSON message: %s", data)
                except json.JSONDecodeError:
                    data = message
                    logging_utility.info("Received raw message: %s", data)
                if isinstance(data, dict) and "content" in data:
                    broadcast_buffer += data["content"]
                else:
                    logging_utility.info("Unexpected message format: %s", data)
        except websockets.ConnectionClosed:
            logging_utility.info("Connection closed.")
        except Exception as e:
            logging_utility.error("Error receiving message: %s", str(e))
        finally:
            await self.ws.close()
            logging_utility.info("Disconnected from server.")

        print(broadcast_buffer)
        return broadcast_buffer

# Example usage of the ShellClient.
async def example_usage():
    config = ShellClientConfig(
        endpoint="ws://localhost:8000/shell",  # Ensure the correct endpoint is used
        thread_id="thread_cJq1gVLSCpLYI8zzZNRbyc",
        timeout=5  # This timeout is now ignored.
    )
    client = ShellClient(config)
    commands = [
        "echo 'Thread-based shell session established'",
        "ls -l",
        "pwd"
    ]
    try:
        result = await client.run(commands)
        logging_utility.info("Final collected shell output: %s", result)
    except Exception as e:
        logging_utility.error("Fatal error: %s", str(e))

if __name__ == "__main__":
    asyncio.run(example_usage())
