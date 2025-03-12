import asyncio
import websockets
import sys
from typing import Optional, List


class ShellClientConfig:
    def __init__(self, endpoint: str = "ws://localhost:8000/ws/shell", timeout: float = 30.0,
                 session_id: Optional[str] = None):
        self.endpoint = endpoint
        self.timeout = timeout
        self.session_id = session_id  # Track session


class ShellClient:
    def __init__(self, config: Optional[ShellClientConfig] = None):
        self.config = config or ShellClientConfig()
        self._ws = None  # WebSocket client connection

    async def connect(self):
        """Connect to the WebSocket server, resuming session if possible."""
        session_url = f"{self.config.endpoint}?session_id={self.config.session_id}" if self.config.session_id else self.config.endpoint
        self._ws = await websockets.connect(session_url, ping_interval=None)

        # Read session ID from the server
        initial_message = await self._ws.recv()
        if initial_message.startswith("SESSION_ID:"):
            self.config.session_id = initial_message.split(":", 1)[1]
            print(f"Connected to session! {self.config.session_id}")

    async def send_commands(self, commands: List[str]):
        """Send a list of commands to the WebSocket server."""
        for cmd in commands:
            await self._ws.send(cmd)
            print(f"Sent: {cmd}")

    async def stream_output(self):
        """Stream output from the WebSocket server and handle reconnection."""
        while True:
            try:
                output = await asyncio.wait_for(self._ws.recv(), timeout=5.0)
                sys.stdout.write(output)
                sys.stdout.flush()
            except asyncio.TimeoutError:
                continue  # Timeout but connection still alive
            except websockets.ConnectionClosed:
                print("\nConnection lost. Attempting to reconnect...")
                await self.reconnect()

    async def reconnect(self):
        """Retry connecting to the last session with exponential backoff."""
        delay = 1
        while True:
            try:
                await self.connect()
                print(f"Reconnected to session {self.config.session_id}")
                await self.stream_output()
                break
            except Exception as e:
                print(f"Reconnection failed ({e}), retrying in {delay} seconds...")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)  # Exponential backoff, max 30s

    async def run(self, commands: List[str], session_id: Optional[str] = None):
        """Main method to run the ShellClient, passing commands and session ID."""
        if session_id:
            self.config.session_id = session_id

        await self.connect()
        await self.send_commands(commands)
        await self.stream_output()


# Example of how this could be called in another script:

async def example_usage():
    client = ShellClient()
    commands = ["echo Hello, world!", "ls", "pwd"]  # Commands to execute on the remote shell
    session_id = None  # Optional, can be passed if reconnecting to an existing session
    await client.run(commands, session_id)


if __name__ == "__main__":
    asyncio.run(example_usage())
