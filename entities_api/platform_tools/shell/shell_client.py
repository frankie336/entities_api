import asyncio
import websockets
from dataclasses import dataclass
from typing import Optional
import sys


@dataclass
class ShellClientConfig:
    endpoint: str = "ws://localhost:8000/ws/shell"
    timeout: float = 30.0


class ShellClient:
    def __init__(self, config: Optional[ShellClientConfig] = None):
        self.config = config or ShellClientConfig()
        self._ws: Optional[websockets.WebSocketClientProtocol] = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def connect(self):
        """Version-compatible connection"""
        self._ws = await websockets.connect(
            self.config.endpoint,
            ping_interval=None,
            # Remove unsupported parameters
        )

    async def close(self):
        if self._ws:
            await self._ws.close()

    async def stream_output(self):
        """Robust output handling with error detection"""
        try:
            while True:
                try:
                    output = await asyncio.wait_for(
                        self._ws.recv(),
                        timeout=1.0
                    )
                    sys.stdout.write(output)
                    sys.stdout.flush()
                except asyncio.TimeoutError:
                    continue
        except websockets.ConnectionClosed as e:
            print(f"\nConnection closed: {e.code} {e.reason}")


async def main():
    client = ShellClient()
    async with client:
        try:
            # Send test command with confirmation
            await client._ws.send("echo 'TEST OUTPUT'\n")
            await client.stream_output()
        except Exception as e:
            print(f"Error: {str(e)}")


if __name__ == "__main__":
    print("=== Testing Output Visibility ===")
    # Windows-specific event loop policy
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nSession terminated")