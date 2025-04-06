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
SHELL_SERVER_URL = os.getenv("SHELL_SERVER_URL", "ws://localhost:8000/ws/computer")


class ShellClient:
    def __init__(self, endpoint: str, room: str, elevated: bool = False, timeout: int = 30):
        self.endpoint = endpoint
        self.room = room
        self.elevated = elevated  # Matches server-side parameter
        self.timeout = timeout
        self.ws = None
        self.lock = asyncio.Lock()

    async def __aenter__(self):
        # Include the elevated parameter in the query string
        conn_str = f"{self.endpoint}?room={self.room}&elevated={str(self.elevated).lower()}"
        logging_utility.info(f"Connecting to WebSocket: {conn_str}")
        self.ws = await websockets.connect(conn_str, ping_interval=self.timeout)
        logging_utility.info(f"Connected to room '{self.room}'")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.ws:
            await self.ws.close()
            logging_utility.info(f"WebSocket closed for room '{self.room}'.")

    async def execute(self, commands: List[str]) -> str:
        """
        Sends all commands and then waits until it receives as many
        "command_complete" signals as commands sent.
        """
        if not self.ws:
            raise RuntimeError("WebSocket connection not established.")

        buffer = ""
        expected_completions = len(commands)
        completions_received = 0

        async def send_commands():
            # Send each command. The server will append an echo marker to each.
            for cmd in commands:
                payload = {"action": "shell_command", "command": cmd}
                await self.ws.send(json.dumps(payload))
                logging_utility.info(f"Sent command: {cmd}")
                # Slight delay between commands
                await asyncio.sleep(0.5)

        async def receive_output():
            nonlocal buffer, completions_received
            try:
                while completions_received < expected_completions:
                    message = await self.ws.recv()
                    data = json.loads(message)
                    msg_type = data.get("type")
                    if msg_type in ["shell_output", "shell_error"]:
                        content = data.get("content", "")
                        buffer += content
                        logging_utility.info(f"Received output chunk: {content.strip()}")
                    elif msg_type == "command_complete":
                        completions_received += 1
                        logging_utility.info(
                            f"Received command complete signal ({completions_received}/{expected_completions})."
                        )
                    else:
                        logging_utility.info(f"Received unrecognized message: {data}")
            except (websockets.exceptions.ConnectionClosed, Exception) as e:
                logging_utility.error(f"Error while receiving output: {str(e)}")

        async def send_disconnect():
            try:
                await self.ws.send(json.dumps({"action": "disconnect"}))
                logging_utility.info("Sent disconnect signal")
            except Exception as e:
                logging_utility.error(f"Failed to send disconnect signal: {str(e)}")

        async with self.lock:
            await send_commands()
            await receive_output()
            await send_disconnect()

        logging_utility.info("Command execution completed.")
        return buffer


async def run_commands(commands: List[str], room: str, elevated: bool = False) -> str:
    async with ShellClient(SHELL_SERVER_URL, room, elevated) as client:
        result = await client.execute(commands)
        return result


def run_commands_sync(commands: List[str], room: str, elevated: bool = False) -> str:
    return asyncio.run(run_commands(commands, room, elevated))
