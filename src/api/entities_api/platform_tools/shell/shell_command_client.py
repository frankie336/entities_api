import logging
import os

from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logging_utility = logging.getLogger("ShellClient")

SHELL_SERVER_URL = os.getenv('SHELL_SERVER_URL', 'ws://sandbox_api:8000/ws/shell')

import asyncio
import json
from typing import List

import websockets

# Assuming logging_utility and SHELL_SERVER_URL are defined elsewhere


class ShellClient:
    def __init__(self, endpoint: str, room: str, timeout: int = 30, idle_timeout: float = 2.0):
        self.endpoint = endpoint
        self.room = room
        self.timeout = timeout
        self.idle_timeout = idle_timeout  # New parameter for idle timeout
        self.ws = None
        self.lock = asyncio.Lock()

    async def __aenter__(self):
        conn_str = f"{self.endpoint}?room={self.room}"
        logging_utility.info(f"Connecting to WebSocket explicitly {conn_str}")
        self.ws = await websockets.connect(conn_str, ping_interval=self.timeout)
        logging_utility.info(f"Connected clearly to room '{self.room}' explicitly")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.ws:
            await self.ws.close()
            logging_utility.info(f"WebSocket explicitly closed for room '{self.room}'.")

    async def execute(self, commands: List[str]) -> str:
        if not self.ws:
            raise RuntimeError("WebSocket connection explicitly not established.")

        buffer = ""

        async def send_commands():
            for cmd in commands:
                payload = {"action": "shell_command", "command": cmd}
                await self.ws.send(json.dumps(payload))
                logging_utility.info(f"Explicitly sent command: {cmd}")

        async def receive_output():
            nonlocal buffer
            try:
                # Use the passed idle_timeout value instead of a hardcoded value.
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
                        if data.get("type") == "shell_output":
                            content = data["content"]
                            buffer += content
                            last_output_time = asyncio.get_event_loop().time()
                            logging_utility.info(f"Explicitly Received shell output chunk: {content.strip()}")
                    except asyncio.TimeoutError:
                        logging_utility.info("Idle explicit timeout reached, command output completed explicitly.")
                        break
            except (websockets.exceptions.ConnectionClosed, Exception) as e:
                logging_utility.error(f"Exception explicitly while receiving shell output: {str(e)}")

        # Run explicitly send_commands and receive_output concurrently
        async with self.lock:
            sender_coro = asyncio.create_task(send_commands())
            receiver_coro = asyncio.create_task(receive_output())
            await sender_coro
            await receiver_coro

        logging_utility.info("Explicit command execution completed explicitly.")
        return buffer

async def run_commands(commands: List[str], room: str, idle_timeout: float = 2.0) -> str:
    async with ShellClient(SHELL_SERVER_URL, room, idle_timeout=idle_timeout) as client:
        result = await client.execute(commands)
        return result

def run_commands_sync(commands: List[str], room: str, idle_timeout: float = 2.0) -> str:
    return asyncio.run(run_commands(commands, room, idle_timeout=idle_timeout))
