import asyncio
import sys
import json
import socketio
import logging
from datetime import datetime, timezone
from typing import List

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class ShellClient:
    def __init__(self, endpoint: str, thread_id: str):
        self.endpoint = endpoint
        self.thread_id = thread_id
        self.namespace = '/shell'

        self.sio = socketio.AsyncClient(
            reconnection=True,
            reconnection_attempts=5,
            reconnection_delay=2000,
            logger=True,
            engineio_logger=True
        )

        self._register_handlers()

    def _register_handlers(self):
        @self.sio.on('connect', namespace=self.namespace)
        async def on_connect():
            logger.debug("Connected to shell namespace")

        @self.sio.on('shell_output', namespace=self.namespace)
        async def on_output(data):
            try:
                payload = json.loads(data['data'])
                if payload.get('thread_id') == self.thread_id:
                    sys.stdout.write(payload['content'])
                    sys.stdout.flush()
            except Exception as e:
                logger.error(f"Output error: {str(e)}")

        @self.sio.on('disconnect', namespace=self.namespace)
        async def on_disconnect():
            logger.info("Disconnected from server")

    async def connect(self):
        await self.sio.connect(
            self.endpoint,
            namespaces=[self.namespace],
            auth={
                self.namespace: {
                    'thread_id': self.thread_id,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
            },
            transports=['websocket'],
            socketio_path='socket.io',
            wait_timeout=15
        )

    async def send_command(self, command: str):
        await self.sio.emit(
            'shell_command',
            {
                'command': command,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'thread_id': self.thread_id
            },
            namespace=self.namespace
        )

    async def run_session(self, commands: List[str]):
        while True:
            try:
                await self.connect()
                logger.info("Session active - Type commands or 'exit' to quit")

                for cmd in commands:
                    await self.send_command(cmd)
                    await asyncio.sleep(0.1)

                while True:
                    await asyncio.sleep(1)

            except (ConnectionError, socketio.exceptions.ConnectionError) as e:
                logger.error(f"Connection error: {str(e)}. Reconnecting...")
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"Fatal error: {str(e)}")
                break
            finally:
                await self.sio.disconnect()


async def main():
    client = ShellClient(
        endpoint="http://localhost:8000",
        thread_id="thread_2ycHHuZk0v3xPei768a9c6"
    )

    try:
        await client.run_session([
            "echo 'Secure session established'",
            "uname -a",
            "whoami",
            "ls -l"
        ])
    except KeyboardInterrupt:
        logger.info("Session terminated by user")


if __name__ == "__main__":
    asyncio.run(main())