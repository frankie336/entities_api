import logging
import os
import asyncio
import json
from typing import List
import websockets
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logging_utility = logging.getLogger("ShellClient")

# Update the endpoint to match the server-side router
SHELL_SERVER_URL = os.getenv('SHELL_SERVER_URL', 'ws://localhost:8000/ws/computer')

class ShellClient:
    def __init__(self, endpoint: str, room: str, elevated: bool = False, timeout: int = 30, idle_timeout: float = 2.0):
        self.endpoint = endpoint
        self.room = room
        self.elevated = elevated  # Renamed to match server-side parameter
        self.timeout = timeout
        self.idle_timeout = idle_timeout  # New parameter for idle timeout
        self.ws = None
        self.lock = asyncio.Lock()

    async def __aenter__(self):
        # Include the elevated parameter in the query string
        conn_str = f"{self.endpoint}?room={self.room}&elevated={str(self.elevated).lower()}"
        logging_utility.info(f"Connecting to WebSocket explicitly {conn_str}")
        self.ws = await websockets.connect(conn_str, ping_interval=self.timeout)
        logging_utility.info(f"Connected clearly to room '{self.room}' explicitly")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.ws:
            await self.ws.close()
            logging_utility.info(f"WebSocket explicitly closed for room '{self.room}'.")

    # In ShellClient class, execute method
    async def execute(self, commands: List[str]) -> str:
        if not self.ws:
            raise RuntimeError("WebSocket connection explicitly not established.")

        buffer = ""

        async def send_commands():
            for cmd in commands:
                # Remove the sudo prefix - the server already handles this based on the elevated parameter
                payload = {"action": "shell_command", "command": cmd}
                await self.ws.send(json.dumps(payload))
                logging_utility.info(f"Explicitly sent command: {cmd}")

                # Add a small delay between commands
                await asyncio.sleep(0.5)

        async def receive_output():
            nonlocal buffer
            try:
                idle_timeout = self.idle_timeout
                last_output_time = asyncio.get_event_loop().time()
                while True:
                    try:
                        timeout_remaining = idle_timeout - (asyncio.get_event_loop().time() - last_output_time)
                        if timeout_remaining <= 0:
                            logging_utility.info("Command explicitly appears complete (idle timeout reached).")
                            break
                        message = await asyncio.wait_for(self.ws.recv(), timeout=timeout_remaining)
                        data = json.loads(message)
                        if data.get("type") in ["shell_output", "shell_error"]:  # Handle both output and error
                            content = data["content"]
                            buffer += content
                            last_output_time = asyncio.get_event_loop().time()
                            logging_utility.info(f"Explicitly Received computer output chunk: {content.strip()}")
                    except asyncio.TimeoutError:
                        logging_utility.info("Idle explicit timeout reached, command output completed explicitly.")
                        break
            except (websockets.exceptions.ConnectionClosed, Exception) as e:
                logging_utility.error(f"Exception explicitly while receiving computer output: {str(e)}")

        # Send disconnect signal when done to properly clean up server resources
        async def send_disconnect():
            try:
                await self.ws.send(json.dumps({"action": "disconnect"}))
                logging_utility.info("Sent explicit disconnect signal")
            except Exception as e:
                logging_utility.error(f"Failed to send disconnect signal: {str(e)}")

        async with self.lock:
            # Send commands first
            await send_commands()

            # Then wait for output
            await receive_output()

            # Finally, send a proper disconnect
            await send_disconnect()

        logging_utility.info("Explicit command execution completed explicitly.")
        return buffer


async def run_commands(commands: List[str], room: str, elevated: bool = False, idle_timeout: float = 2.0) -> str:
    async with ShellClient(SHELL_SERVER_URL, room, elevated, idle_timeout=idle_timeout) as client:
        result = await client.execute(commands)
        return result

def run_commands_sync(commands: List[str], room: str, elevated: bool = False, idle_timeout: float = 2.0) -> str:
    return asyncio.run(run_commands(commands, room, elevated, idle_timeout=idle_timeout))