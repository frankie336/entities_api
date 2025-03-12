import asyncio
import sys
from typing import Optional, List

import socketio

from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()




class ShellClientConfig:
    def __init__(self,
                 endpoint: str = "http://localhost:8000",
                 namespace: str = "/shell",
                 thread_id: Optional[str] = None):
        self.endpoint = endpoint
        self.namespace = namespace
        self.thread_id = thread_id
        self.transport = 'websocket'


class ShellClient:
    def __init__(self, config: Optional[ShellClientConfig] = None):
        self.config = config or ShellClientConfig()
        self.sio = socketio.AsyncClient(logger=True, engineio_logger=True)
        self._configure_handlers()
        self.active_tasks = []  # Track active tasks for cleanup

    def _configure_handlers(self):
        namespace = self.config.namespace

        @self.sio.on('connect', namespace=namespace)
        async def handle_connect():
            logging_utility.debug(f"Namespace {namespace} connected")

        @self.sio.on('session_ready', namespace=namespace)
        async def handle_session_ready(data):
            logging_utility.info(f"Session ready: {data}")
            self.config.thread_id = data['thread_id']

        # Update the shell_output handler
        @self.sio.on('shell_output', namespace=namespace)
        async def handle_shell_output(data):
            """Handle real-time shell output"""
            try:
                if data.get('thread_id') == self.config.thread_id:
                    sys.stdout.write(data['data'])
                    sys.stdout.flush()
                    logging_utility.debug(f"Received {len(data['data'])} bytes")
                else:
                    logging_utility.warning(f"Ignored output for thread {data.get('thread_id')}")
            except Exception as e:
                logging_utility.error(f"Output handling error: {str(e)}")

        @self.sio.on('disconnect', namespace=namespace)
        async def handle_disconnect():
            logging_utility.info("Disconnected from namespace")

            # Check if there are any active tasks or commands to clean up
            if hasattr(self, 'active_tasks'):
                for task in self.active_tasks:
                    if not task.done():
                        logging_utility.info(f"Cancelling active task: {task}")
                        task.cancel()

            # Ensure that any open resources are cleaned up
            logging_utility.info("Client resources cleaned up.")
            await self.sio.disconnect()

        @self.sio.event
        async def reconnect():
            logging_utility.info("Reconnected to the server.")

        @self.sio.event
        async def connect_error(data):
            logging_utility.error(f"Connection failed: {data}")

        @self.sio.event
        async def reconnect_error(data):
            logging_utility.error(f"Reconnection failed: {data}")

    async def connect(self):
        """Connect with detailed logging"""
        logging_utility.debug(f"Connecting to {self.config.endpoint}")
        logging_utility.debug(f"Using thread ID: {self.config.thread_id}")
        logging_utility.debug(f"Using namespace: {self.config.namespace}")

        try:
            await self.sio.connect(
                self.config.endpoint,
                transports=[self.config.transport],
                namespaces=[self.config.namespace],
                auth={'thread_id': self.config.thread_id},  # Verified auth
                wait_timeout=15
            )
            logging_utility.debug("Connection attempt completed")
        except Exception as e:
            logging_utility.error(f"Connection failed: {str(e)}")
            raise

    async def send_command(self, command: str):
        logging_utility.debug(f"Sending command: {command[:50]}...")
        await self.sio.emit(
            'shell_command',
            {'thread_id': self.config.thread_id, 'command': command},
            namespace=self.config.namespace
        )

    async def run(self, commands: List[str], thread_id: Optional[str] = None):
        self.config.thread_id = thread_id or self.config.thread_id
        logging_utility.info(f"Starting session with thread ID: {self.config.thread_id}")

        try:
            await self.connect()
            logging_utility.info("Connection established, sending commands...")

            for cmd in commands:
                await self.send_command(cmd)
                logging_utility.debug(f"Sent command: {cmd}")

            logging_utility.info("Awaiting output...")
            while self.sio.connected:
                await asyncio.sleep(0.1)

        except Exception as e:
            logging_utility.error(f"Runtime error: {str(e)}")
        finally:
            await self.sio.disconnect()
            logging_utility.info("Disconnected")


async def example_usage():
    client = ShellClient(ShellClientConfig(
        thread_id="thread_2ycHHuZk0v3xPei768a9c6",
        endpoint="http://localhost:8000"
    ))

    commands = [
        "echo 'Thread-based shell session established'",
        "ls -l",
        "pwd"
    ]

    try:
        await client.run(commands)
    except Exception as e:
        logging_utility.error(f"Fatal error: {str(e)}")


if __name__ == "__main__":
    asyncio.run(example_usage())






