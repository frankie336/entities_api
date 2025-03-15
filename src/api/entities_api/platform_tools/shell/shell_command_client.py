import asyncio
import json
from typing import Optional, List
import websockets
from src.api.entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()


# --- Singleton Connection Manager ---
class ShellConnectionManager:
    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._clients = {}
        return cls._instance

    async def get_client(self, thread_id: str) -> "ShellClient":
        async with self._lock:
            if thread_id not in self._clients:
                config = ShellClientConfig(thread_id=thread_id)
                client = ShellClient(config)
                await client.connect()
                await client.join_room()
                self._clients[thread_id] = client
            return self._clients[thread_id]

    async def cleanup(self, thread_id: str):
        async with self._lock:
            if thread_id in self._clients:
                await self._clients[thread_id].close()
                del self._clients[thread_id]


# --- Modified Shell Client ---
class ShellClientConfig:
    def __init__(self,
                 endpoint: str = "ws://localhost:8000/shell",
                 thread_id: Optional[str] = None,
                 timeout: int = 30):  # Increased timeout for persistent connections
        self.endpoint = endpoint
        self.thread_id = thread_id
        self.timeout = timeout


class ShellClient:
    def __init__(self, config: ShellClientConfig):
        self.config = config
        self.ws = None
        self._keep_alive = True

    async def connect(self):
        """Connection handled by manager"""
        query = f"?thread_id={self.config.thread_id}&user_id=system"
        self.ws = await websockets.connect(
            f"{self.config.endpoint}{query}",
            ping_interval=self.config.timeout
        )

    async def join_room(self):
        """Room joining handled by manager"""
        await self.ws.send(json.dumps({
            "action": "join_room",
            "room": self.config.thread_id
        }))

    async def execute(self, commands: List[str]) -> str:
        """Core execution method without connection management"""
        for cmd in commands:
            await self.ws.send(json.dumps({
                "action": "shell_command",
                "command": cmd,
                "thread_id": self.config.thread_id
            }))

        buffer = ""
        try:
            while self._keep_alive:
                message = await asyncio.wait_for(
                    self.ws.recv(),
                    timeout=self.config.timeout
                )
                data = json.loads(message)
                if "content" in data:
                    buffer += data["content"]
        except (asyncio.TimeoutError, websockets.ConnectionClosed):
            pass
        return buffer

    async def close(self):
        """Graceful closure"""
        self._keep_alive = False
        if self.ws:
            await self.ws.close()
            self.ws = None


# --- Updated Usage Pattern ---
async def computer(commands: List[str], thread_id: str) -> str:
    manager = ShellConnectionManager()
    client = await manager.get_client(thread_id)
    try:
        return await client.execute(commands)
    finally:
        # Keep connection alive for subsequent commands
        # Uncomment below to force close after each execution
        # await manager.cleanup(thread_id)
        pass


# --- Example Usage with Persistent Connection ---
async def example_usage():
    thread_id = "thread_cJq1gVLSCpLYI8zzZNRbyc"

    # First command sequence - establishes connection
    result1 = await computer([
        "echo 'Starting session'",
        "ls -l"
    ], thread_id)
    print("First result:", result1)

    # Second command sequence - reuses connection
    result2 = await computer([
        "echo 'Reusing existing connection'",
        "pwd"
    ], thread_id)
    print("Second result:", result2)

    # Cleanup when done
    manager = ShellConnectionManager()
    await manager.cleanup(thread_id)


if __name__ == "__main__":
    asyncio.run(example_usage())