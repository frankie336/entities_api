import asyncio
import websockets
import json
import logging
import os
from typing import List
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logging_utility = logging.getLogger("ShellClient")

SHELL_SERVER_URL = os.getenv('SHELL_SERVER_URL', 'ws://sandbox_api:8000/ws/shell')

class ShellClient:
    def __init__(self, endpoint: str, room: str, timeout: int = 30):
        self.endpoint = endpoint
        self.room = room
        self.timeout = timeout
        self.ws = None
        self.lock = asyncio.Lock()

    async def __aenter__(self):
        conn_str = f"{self.endpoint}?room={self.room}"
        logging_utility.info(f"Connecting to WebSocket {conn_str}")
        self.ws = await websockets.connect(conn_str, ping_interval=self.timeout)
        logging_utility.info(f"Connected successfully to room '{self.room}'")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.ws:
            await self.ws.close()
            logging_utility.info(f"WebSocket for room '{self.room}' closed.")

    async def execute(self, commands: List[str]) -> str:
        if not self.ws:
            raise RuntimeError("WebSocket connection not established.")
        buffer = ""

        async def send_commands():
            for cmd in commands:
                payload = {"action": "shell_command", "command": cmd}
                await self.ws.send(json.dumps(payload))
                logging_utility.info(f"Sent command: {cmd}")

        async def receive_output():
            nonlocal buffer
            try:
                while True:
                    message = await asyncio.wait_for(self.ws.recv(), timeout=self.timeout)
                    data = json.loads(message)
                    if data.get("type") == "shell_output":
                        content = data["content"]
                        buffer += content
                        logging_utility.info(f"Received shell output: {content.strip()}")
            except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
                logging_utility.info("Stopped receiving (timeout/closed).")

        # Send and then collect all output
        async with self.lock:
            await send_commands()
            await receive_output()

        logging_utility.info("Command execution completed.")
        return buffer

async def run_commands(commands: List[str], room: str) -> str:
    async with ShellClient(SHELL_SERVER_URL, room) as client:
        result = await client.execute(commands)
        return result

def run_commands_sync(commands: List[str], room: str) -> str:
    return asyncio.run(run_commands(commands, room))