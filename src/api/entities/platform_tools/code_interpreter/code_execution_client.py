import asyncio
import json
import os
from dataclasses import dataclass
from typing import Optional, Dict, Any, AsyncGenerator, Generator

import websockets
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
from websockets.legacy.protocol import WebSocketCommonProtocol

from entities.services.logging_service import LoggingUtility

load_dotenv()

logging_utility = LoggingUtility()

@dataclass
class ExecutionClientConfig:
    endpoint: str = os.getenv('CODE_EXECUTION_URL')
    timeout: float = 15.0
    retries: int = 3
    retry_delay: float = 2.0

class CodeExecutionClientError(Exception):
    """Base exception for execution client errors"""
    pass

class ExecutionTimeoutError(CodeExecutionClientError):
    """Raised when server response times out"""
    pass

class ExecutionSecurityViolation(CodeExecutionClientError):
    """Raised when code violates security policies"""
    pass

class CodeExecutionClient:
    def __init__(self, config: Optional[ExecutionClientConfig] = None):
        self.config = config or ExecutionClientConfig()
        self._connection: Optional[WebSocketCommonProtocol] = None
        logging_utility.info("CodeExecutionClient initialized with endpoint: %s", self.config.endpoint)

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(2.0),
        retry=retry_if_exception_type((OSError, ConnectionRefusedError)),
    )
    async def connect(self):
        """Establishes WebSocket connection with timeout."""
        try:
            logging_utility.info("Attempting to connect to WebSocket endpoint: %s", self.config.endpoint)
            self._connection = await asyncio.wait_for(
                websockets.connect(self.config.endpoint, ping_interval=None),
                timeout=self.config.timeout
            )
            logging_utility.info("Successfully connected to WebSocket endpoint.")
        except asyncio.TimeoutError as e:
            logging_utility.error("Connection to %s timed out", self.config.endpoint)
            raise ExecutionTimeoutError(f"Connection to {self.config.endpoint} timed out") from e

    async def close(self):
        """Gracefully closes connection."""
        if self._connection:
            logging_utility.info("Closing WebSocket connection.")
            await self._connection.close()
            self._connection = None

    async def execute_code(self, code: str, **metadata: Dict[str, Any]) -> AsyncGenerator[str, None]:
        if not self._connection:
            logging_utility.error("Execution attempt without active connection.")
            raise CodeExecutionClientError("Not connected to execution endpoint")

        try:
            logging_utility.info("Sending code execution request.")
            await self._connection.send(json.dumps({"code": code, "metadata": metadata}))

            while True:
                message = await self._connection.recv()
                if not message:
                    continue

                try:
                    data = json.loads(message)
                    if isinstance(data, dict):
                        if 'error' in data:
                            logging_utility.error("ExecutionSecurityViolation: %s", data['error'])
                            raise ExecutionSecurityViolation(data['error'])
                        if 'status' in data:
                            yield json.dumps({'type': 'status', 'content': data['status']})
                            break
                        if 'output' in data:
                            yield json.dumps({'type': 'output', 'content': data['output']})
                    else:
                        yield json.dumps({'type': 'hot_code_output', 'content': str(data)})
                except json.JSONDecodeError:
                    logging_utility.warning("Received non-JSON output: %s", message)
                    yield json.dumps({'type': 'hot_code_output', 'content': message})
        except websockets.exceptions.ConnectionClosed:
            logging_utility.error("WebSocket connection closed unexpectedly.")
            raise CodeExecutionClientError("Connection closed unexpectedly")

class StreamOutput:
    def stream_output(self, code: str) -> Generator[str, None, None]:
        """Synchronous generator bridge for async execution"""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        async def _async_wrapper() -> AsyncGenerator[str, None]:
            async with CodeExecutionClient() as client:
                async for chunk in client.execute_code(code):
                    yield chunk

        async_gen = _async_wrapper()
        try:
            while True:
                yield loop.run_until_complete(async_gen.__anext__())
        except StopAsyncIteration:
            pass


if __name__ == '__main__':
    logging_utility.info("Starting code execution.")
    output = StreamOutput()

    # Create a file and write to it
    with open("output_file.txt", "w") as file:
        file.write("This file was created by the script.\n")

    for chunk in output.stream_output("print('Hello, world!')"):
        logging_utility.info("Received chunk: %s", json.loads(chunk))