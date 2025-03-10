import asyncio
import json
import websockets
from dataclasses import dataclass
from typing import Optional, Dict, Any, AsyncGenerator, Generator
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type, before_sleep_log

from entities_api.platform_tools.web.web_search_handler import logging_utility


@dataclass
class ExecutionClientConfig:
    endpoint: str = "ws://localhost:9000/ws/execute"
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
        self._connection: Optional[websockets.WebSocketClientProtocol] = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    @retry(
        stop=stop_after_attempt(3),  # config.retries + 1 (original starts at 0)
        wait=wait_fixed(2.0),  # config.retry_delay
        retry=retry_if_exception_type((OSError, ConnectionRefusedError)),
        before_sleep=before_sleep_log(None, logging_utility.info("sleep")),
        reraise=True
    )
    async def connect(self):
        """Establishes WebSocket connection with timeout"""
        try:
            self._connection = await asyncio.wait_for(
                websockets.connect(self.config.endpoint, ping_interval=None),
                timeout=self.config.timeout
            )
        except asyncio.TimeoutError as e:
            raise ExecutionTimeoutError(
                f"Connection to {self.config.endpoint} timed out"
            ) from e

    async def close(self):
        """Gracefully closes connection"""
        if self._connection:
            await self._connection.close()
            self._connection = None

    async def execute_code(
            self,
            code: str,
            **metadata: Dict[str, Any]
    ) -> AsyncGenerator[str, None]:
        if not self._connection:
            raise CodeExecutionClientError("Not connected to execution endpoint")

        try:
            await self._connection.send(json.dumps({
                "code": code,
                "metadata": metadata
            }))

            while True:
                message = await self._connection.recv()
                if not message:
                    continue

                try:
                    data = json.loads(message)
                    if isinstance(data, dict):
                        if 'error' in data:
                            raise ExecutionSecurityViolation(data['error'])
                        if 'status' in data:
                            yield json.dumps({
                                'type': 'status',
                                'content': data['status']
                            })
                            break
                        if 'output' in data:
                            yield json.dumps({
                                'type': 'output',
                                'content': data['output']
                            })
                    else:
                        yield json.dumps({
                            'type': 'hot_code_output',
                            'content': str(data)
                        })
                except json.JSONDecodeError:
                    yield json.dumps({
                        'type': 'hot_code_output',
                        'content': message
                    })

        except websockets.exceptions.ConnectionClosed:
            raise CodeExecutionClientError("Connection closed unexpectedly")

async def run_client(code):
    config = ExecutionClientConfig()
    async with CodeExecutionClient(config) as client:
        async for chunk in client.execute_code(code):
            print(f"Received: {chunk}")


code = """


class MathOperations:
    def __init__(self):
        pass

    def power(self, base: int, exponent: int) -> int:
   
        result = 1
        for _ in range(exponent):
            result *= base
        return result

    def matrix_multiply(self, matrix1: list, matrix2: list) -> list:
     
        # Validate matrix dimensions
        if (len(matrix1) != 2 or len(matrix1[0]) != 2 or
            len(matrix2) != 2 or len(matrix2[0]) != 2):
            raise ValueError("Both matrices must be 2x2")

        # Initialize result matrix with zeros
        result = [[0 for _ in range(2)] for _ in range(2)]

        # Perform multiplication
        for i in range(2):
            for j in range(2):
                for k in range(2):
                    result[i][j] += matrix1[i][k] * matrix2[k][j]
        return result



if __name__ == "__main__":
    # Create an instance of MathOperations
    ops = MathOperations()

    # Exponentiation: Compute 2^10
    print("2^10:", ops.power(2, 10))  # Output: 2^10: 1024

    # Matrix Multiplication: Multiply two 2x2 matrices
    matrix1 = [[1, 2], [3, 4]]
    matrix2 = [[5, 6], [7, 8]]
    print("Matrix Multiplication Result:", ops.matrix_multiply(matrix1, matrix2))
    # Output: Matrix Multiplication Result: [[19, 22], [43, 50]]


""".strip()


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
    output = StreamOutput()
    for chunk in output.stream_output(code):
        print("Received chunk:", json.loads(chunk))