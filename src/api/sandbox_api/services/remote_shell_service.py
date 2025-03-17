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
                # Check if the WebSocket is still open
                if client.ws and not client.ws.closed:
                    return client
                else:
                    # Clean up the stale client
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
                # Make sure to close the client if there's an error
                await client.close()
                raise e

    async def cleanup(self, thread_id: str):
        async with self._lock:
            if thread_id in self._clients:
                try:
                    await self._clients[thread_id].close()
                except Exception as e:
                    logging_utility.error(f"Error closing client: {e}")
                finally:
                    del self._clients[thread_id]


# --- Modified Shell Client ---
class ShellClientConfig:
    def __init__(self,
                 endpoint: str = os.getenv('SHELL_SERVER_URL'),
                 thread_id: Optional[str] = None,
                 timeout: int = 30,  # Increased timeout for persistent connections
                 command_timeout: int = 10):  # Timeout for individual command execution
        self.endpoint = endpoint
        self.thread_id = thread_id
        self.timeout = timeout
        self.command_timeout = command_timeout


class ShellClient:
    def __init__(self, config: ShellClientConfig):
        self.config = config
        self.ws = None
        self._keep_alive = True
        self._recv_lock = asyncio.Lock()  # Add a lock for receiving messages

    async def connect(self):
        """Connection handled by manager"""
        query = f"?thread_id={self.config.thread_id}&user_id=system"
        try:
            self.ws = await websockets.connect(
                f"{self.config.endpoint}{query}",
                ping_interval=self.config.timeout
            )
            logging_utility.info(f"Connected to shell server for thread {self.config.thread_id}")
        except Exception as e:
            logging_utility.error(f"Failed to connect to shell server: {e}")
            raise

    async def join_room(self):
        """Room joining handled by manager"""
        try:
            await self.ws.send(json.dumps({
                "action": "join_room",
                "room": self.config.thread_id
            }))
            logging_utility.info(f"Joined room {self.config.thread_id}")
        except Exception as e:
            logging_utility.error(f"Failed to join room: {e}")
            raise

    async def execute(self, commands: List[str]) -> str:
        """Core execution method with protection against concurrent access"""
        if not self.ws or self.ws.closed:
            logging_utility.error("WebSocket is not connected")
            await self.reconnect()

        # Send all commands first
        try:
            for cmd in commands:
                await self.ws.send(json.dumps({
                    "action": "shell_command",
                    "command": cmd,
                    "thread_id": self.config.thread_id
                }))
                logging_utility.debug(f"Sent command: {cmd}")
        except Exception as e:
            logging_utility.error(f"Error sending command: {e}")
            await self.reconnect()
            return f"Error: Failed to send command - {str(e)}"

        buffer = ""
        # Use the lock to ensure only one coroutine can receive at a time
        async with self._recv_lock:
            try:
                # Add a timeout to prevent indefinite waiting
                start_time = asyncio.get_event_loop().time()
                last_data_time = start_time
                idle_timeout = 2.0  # Consider command complete if no data received for this time

                while self._keep_alive:
                    # Check if we've exceeded the maximum execution time
                    current_time = asyncio.get_event_loop().time()
                    if current_time - start_time > self.config.timeout:
                        logging_utility.info(f"Command execution timed out after {self.config.timeout}s")
                        break

                    # Check if we've been idle too long (indicates command completion)
                    if buffer and current_time - last_data_time > idle_timeout:
                        logging_utility.debug("Command appears complete (idle timeout)")
                        break

                    try:
                        message = await asyncio.wait_for(
                            self.ws.recv(),
                            timeout=1.0  # Shorter timeout for more responsive checking
                        )
                        last_data_time = asyncio.get_event_loop().time()

                        try:
                            data = json.loads(message)
                            if "content" in data:
                                buffer += data["content"]
                                logging_utility.debug(f"Received content chunk, buffer now {len(buffer)} bytes")
                            # If server sends explicit completion signal
                            if "command_complete" in data:
                                logging_utility.debug("Received explicit command completion signal")
                                break
                        except json.JSONDecodeError:
                            # Handle plain text responses
                            buffer += message
                            logging_utility.debug(f"Received plain text, buffer now {len(buffer)} bytes")

                    except asyncio.TimeoutError:
                        # Just a check interval timeout, continue the loop
                        pass

            except websockets.ConnectionClosed as e:
                logging_utility.error(f"WebSocket connection closed during execution: {e}")
                await self.reconnect()
            except Exception as e:
                logging_utility.error(f"Error during command execution: {e}")

        return buffer

    async def reconnect(self):
        """Attempt to reconnect if the connection is lost"""
        try:
            if self.ws:
                await self.ws.close()
        except:
            pass  # Ignore errors while closing

        try:
            await self.connect()
            await self.join_room()
            logging_utility.info("Successfully reconnected to shell server")
        except Exception as e:
            logging_utility.error(f"Failed to reconnect: {e}")
            raise

    async def close(self):
        """Graceful closure"""
        self._keep_alive = False
        if self.ws:
            try:
                await self.ws.close()
                logging_utility.info(f"Closed WebSocket connection for thread {self.config.thread_id}")
            except Exception as e:
                logging_utility.error(f"Error closing WebSocket: {e}")
            finally:
                self.ws = None


