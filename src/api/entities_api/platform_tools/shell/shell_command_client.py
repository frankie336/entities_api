import os
import asyncio
import json
from typing import Optional, List
import websockets
from entities_api.services.logging_service import LoggingUtility

from dotenv import load_dotenv

load_dotenv()

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
            if thread_id in self._clients:
                client = self._clients[thread_id]
                # Instead of checking a specific attribute, test the connection
                try:
                    # Just check if we can send a ping
                    if not client.ws:
                        raise ValueError("No WebSocket connection")
                    client._last_used = asyncio.get_event_loop().time()
                    return client
                except Exception:
                    # If anything goes wrong, clean up and create a new client
                    await self.cleanup(thread_id)

            # Create a new client
            config = ShellClientConfig(thread_id=thread_id)
            client = ShellClient(config)
            try:
                await client.connect()
                await client.join_room()
                self._clients[thread_id] = client
                return client
            except Exception as e:
                await client.close()
                raise e

    async def cleanup(self, thread_id: str):
        async with self._lock:
            if thread_id in self._clients:
                try:
                    await self._clients[thread_id].close()
                except Exception as e:
                    logging_utility.error(f"Error during cleanup: {e}")
                finally:
                    del self._clients[thread_id]


# --- Modified Shell Client ---
class ShellClientConfig:
    def __init__(self,
                 endpoint: str = os.getenv('SHELL_SERVER_URL'),
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
        self._recv_lock = asyncio.Lock()  # Add a lock for receiving messages
        self._last_used = asyncio.get_event_loop().time()

    async def connect(self):
        """Connection handled by manager"""
        logging_utility.info(f"Connecting to shell server for thread {self.config.thread_id}")
        query = f"?thread_id={self.config.thread_id}&user_id=system"
        try:
            self.ws = await websockets.connect(
                f"{self.config.endpoint}{query}",
                ping_interval=self.config.timeout
            )
            logging_utility.info(f"Connected successfully to {self.config.endpoint}")
        except Exception as e:
            logging_utility.error(f"Connection failed: {e}")
            raise

    async def join_room(self):
        """Room joining handled by manager"""
        if not self.ws:
            logging_utility.error("Cannot join room: No WebSocket connection")
            raise ValueError("No WebSocket connection")

        try:
            await self.ws.send(json.dumps({
                "action": "join_room",
                "room": self.config.thread_id
            }))
            logging_utility.info(f"Joined room: {self.config.thread_id}")
        except Exception as e:
            logging_utility.error(f"Failed to join room: {e}")
            raise

    async def execute(self, commands: List[str]) -> str:
        """Core execution method with locking to prevent concurrent access"""
        if not self.ws:
            logging_utility.warning("No active WebSocket connection, creating new connection")
            try:
                await self.connect()
                await self.join_room()
            except Exception as e:
                logging_utility.error(f"Reconnection failed: {e}")
                return f"Connection error: {str(e)}"

        # Send all commands first
        try:
            for cmd in commands:
                logging_utility.info(f"Sending command: {cmd}")
                await self.ws.send(json.dumps({
                    "action": "shell_command",
                    "command": cmd,
                    "thread_id": self.config.thread_id
                }))
        except Exception as e:
            logging_utility.error(f"Failed to send commands: {e}")
            self.ws = None  # Mark connection as failed
            return f"Send error: {str(e)}"

        buffer = ""
        # Use the lock to ensure only one coroutine can receive at a time
        async with self._recv_lock:
            try:
                # Add a timeout to prevent indefinite waiting
                start_time = asyncio.get_event_loop().time()
                last_data_time = start_time

                while self._keep_alive:
                    current_time = asyncio.get_event_loop().time()

                    # Exit if we've exceeded the maximum time
                    if current_time - start_time > self.config.timeout:
                        logging_utility.info("Command timeout reached")
                        break

                    # Exit if we've been idle for a while after getting data
                    if buffer and current_time - last_data_time > 2.0:
                        logging_utility.info("Command appears complete (idle timeout)")
                        break

                    try:
                        message = await asyncio.wait_for(
                            self.ws.recv(),
                            timeout=1.0
                        )

                        try:
                            data = json.loads(message)
                            if "content" in data:
                                buffer += data["content"]
                                last_data_time = current_time
                                logging_utility.debug(f"Received content, buffer length: {len(buffer)}")
                        except json.JSONDecodeError:
                            # Handle plain text responses
                            buffer += message
                            last_data_time = current_time
                            logging_utility.debug(f"Received text, buffer length: {len(buffer)}")

                    except asyncio.TimeoutError:
                        # Just a checking interval
                        continue
                    except Exception as e:
                        logging_utility.error(f"Error receiving data: {e}")
                        self.ws = None  # Mark connection as failed
                        break

            except Exception as e:
                logging_utility.error(f"Execution error: {e}")
                self.ws = None  # Mark connection as failed

        if not buffer:
            logging_utility.warning("No output received from command execution")

        return buffer

    async def close(self):
        """Graceful closure"""
        self._keep_alive = False
        if self.ws:
            try:
                await self.ws.close()
                logging_utility.info(f"Closed WebSocket for thread {self.config.thread_id}")
            except Exception as e:
                logging_utility.error(f"Error closing WebSocket: {e}")
            finally:
                self.ws = None


# --- Updated Usage Pattern ---
async def computer(commands: List[str], thread_id: str) -> str:
    manager = ShellConnectionManager()
    try:
        client = await manager.get_client(thread_id)
        result = await client.execute(commands)
        return result
    except Exception as e:
        logging_utility.error(f"Command execution failed: {str(e)}")
        # Try to cleanup the connection in case of failure
        await manager.cleanup(thread_id)
        return f"Execution failed: {str(e)}"


# --- Example Usage with Persistent Connection ---
async def example_usage():
    thread_id = "thread_cJq1gVLSCpLYI8zzZNRbyc"

    try:
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
    finally:
        # Cleanup when done
        manager = ShellConnectionManager()
        await manager.cleanup(thread_id)


if __name__ == "__main__":
    asyncio.run(example_usage())