# entities_api/platform_tools/handlers/computer/shell_command_client.py
import asyncio
import json
import logging
import os
from typing import List, AsyncGenerator

import websockets
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logging_utility = logging.getLogger("ShellClient")
SHELL_SERVER_URL = os.getenv("SHELL_SERVER_URL", "ws://localhost:8000/ws/computer")


class ShellClient:
    def __init__(
        self,
        endpoint: str,
        room: str,
        token: str,
        elevated: bool = False,
        timeout: int = 30,
    ):
        self.endpoint = endpoint
        self.room = room
        self.token = token
        self.elevated = elevated
        self.timeout = timeout
        self.ws = None
        self.lock = asyncio.Lock()

    async def __aenter__(self):
        conn_str = f"{self.endpoint}?room={self.room}&elevated={str(self.elevated).lower()}&token={self.token}"
        logging_utility.info(f"Connecting to WebSocket: {conn_str}")
        self.ws = await websockets.connect(conn_str, ping_interval=self.timeout)
        logging_utility.info(f"Connected to room '{self.room}'")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.ws:
            await self.ws.close()
            logging_utility.info(f"WebSocket closed for room '{self.room}'.")

    async def execute_stream(self, commands: List[str]) -> AsyncGenerator[str, None]:
        """
        Sends commands and YIELDS output chunks in real-time.
        """
        if not self.ws:
            raise RuntimeError("WebSocket connection not established.")

        expected_completions = len(commands)
        completions_received = 0

        async with self.lock:
            # 1. Send all commands
            for cmd in commands:
                payload = {"action": "shell_command", "command": cmd}
                await self.ws.send(json.dumps(payload))
                logging_utility.info(f"Sent command: {cmd}")
                await asyncio.sleep(0.1) # Small delay to ensure order

            # 2. Receive loop (Yielding chunks)
            try:
                while completions_received < expected_completions:
                    message = await self.ws.recv()
                    data = json.loads(message)
                    msg_type = data.get("type")

                    if msg_type in ["shell_output", "shell_error"]:
                        content = data.get("content", "")
                        # Log it for debugging
                        logging_utility.info(f"Received output chunk: {content.strip()}")
                        # CRITICAL: Yield immediately to the upper layers
                        yield content

                    elif msg_type == "command_complete":
                        completions_received += 1
                        logging_utility.info(
                            f"Received command complete signal ({completions_received}/{expected_completions})."
                        )
                    else:
                        logging_utility.info(f"Received unrecognized message: {data}")

                # 3. Disconnect signal
                await self.ws.send(json.dumps({"action": "disconnect"}))
                logging_utility.info("Sent disconnect signal")

            except (websockets.exceptions.ConnectionClosed, Exception) as e:
                logging_utility.error(f"Error while receiving output: {str(e)}")
                yield f"\n[Connection Error: {str(e)}]\n"

        logging_utility.info("Command execution completed.")

    # Backward compatibility for sync wrappers if needed
    async def execute(self, commands: List[str]) -> str:
        full_output = ""
        async for chunk in self.execute_stream(commands):
            full_output += chunk
        return full_output


# --- UPDATED ASYNC GENERATOR ---
async def run_commands(
    commands: List[str], room: str, token: str, elevated: bool = False
) -> AsyncGenerator[str, None]:
    """
    Now returns an AsyncGenerator instead of a String.
    """
    async with ShellClient(SHELL_SERVER_URL, room, token, elevated) as client:
        async for chunk in client.execute_stream(commands):
            yield chunk


# --- SYNC WRAPPER UPDATED ---
def run_commands_sync(
    commands: List[str], room: str, token: str, elevated: bool = False
) -> str:
    """
    Wraps the streaming generator into a single blocking string return.
    """
    async def _collect():
        buffer = ""
        async for chunk in run_commands(commands, room, token, elevated):
            buffer += chunk
        return buffer

    return asyncio.run(_collect())
