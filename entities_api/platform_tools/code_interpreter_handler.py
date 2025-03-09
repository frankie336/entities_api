import json
import os
import re
import time

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from entities_api.clients.client_code_executor import ClientCodeService
from entities_api.services.logging_service import LoggingUtility


class CodeExecutionHandler:
    def __init__(self):
        self.logging_utility = LoggingUtility()

    def normalize_code(self, code: str) -> str:
        """
        Normalizes the inbound code by handling special characters, ensuring valid Python syntax,
        and sanitizing non-ASCII characters and escape sequences. Additionally, automatically wraps
        single expressions in a print statement to ensure output is captured.

        Args:
            code (str): The code snippet to normalize.

        Returns:
            str: The normalized code.
        """
        # Replace curly quotes with straight quotes
        code = code.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")

        # Replace Unicode superscript ² with **2 for exponentiation
        code = code.replace('\u00b2', '**2')

        # Replace double backslashes with single backslashes
        code = code.replace('\\\\', '\\')

        # Normalize escaped newlines and tabs
        code = code.encode('utf-8').decode('unicode_escape')

        # Remove any remaining non-ASCII characters
        code = re.sub(r'[^\x00-\x7F]+', '', code)

        # Automatically wrap single expressions in print statements
        if re.match(r'^[\w\.]+\s*\(.*\)\s*$', code.strip()):
            code = f"print({code.strip()})"

        return code


    def execute_code(self, code: str, language: str = "python", user_id: str = "test_user") -> str:
        """
        Executes the provided code in the given language using the code_executor_service and returns
        the result or error in a structured JSON format with the keys ‘result’ for output and ‘error’
        for any errors encountered.

        The response will include both the executed code and the output/error.

        Args:
            code (str): The code snippet to execute.
            language (str): The programming language of the code (default is "python").
            user_id (str): The user ID requesting the code execution. Defaults to 'test_user' if not provided.

        Returns:
            str: A JSON-formatted string with either 'result' for successful execution or 'error' if something went wrong.
                 The 'result' key will contain the executed code and the corresponding output.
        """
        # Ensure user_id is valid, fallback to 'test_user' if invalid
        if not user_id:
            self.logging_utility.warning("User ID is null or invalid. Falling back to 'test_user'.")
            user_id = "test_user"

        self.logging_utility.info("Normalizing code for user: %s", user_id)

        # Normalize the inbound code to handle potential formatting issues
        normalized_code = self.normalize_code(code)

        self.logging_utility.info("Executing code for user: %s", user_id)

        try:
            # Execute the code using the OllamaClient's code_executor_service
            client = ClientCodeService(
                sandbox_server_url=os.getenv('CODE_SERVER_URL', 'http://localhost:9000/v1/execute_code')
            )

            response = client.execute_code(code=normalized_code, language=language, user_id=user_id)

            # Check if there was an error
            if response.get('error'):
                self.logging_utility.error("Code execution error: %s", response['error'])
                return json.dumps({
                    "error": {
                        "code": normalized_code,
                        "message": response['error']
                    }
                })

            # Otherwise, return the output along with the code as part of the 'result' key
            self.logging_utility.info("Code executed successfully. Result: %s", response['output'])
            return json.dumps({
                "result": {
                    "code": normalized_code,
                    "output": response['output']

                }
            })

        except Exception as e:
            error_message = f"Error executing code: {str(e)}"
            self.logging_utility.error(error_message)
            return json.dumps({
                "error": {
                    "code": normalized_code,
                    "message": error_message
                }
            })
class StreamingCodeExecutionHandler(CodeExecutionHandler):
    def __init__(self):
        super().__init__()
        self.active_processes = {}
        self.security_profile = {
            "firejail_args": [
                "--noprofile",
                "--private-tmp",
                "--nogroups",
                "--nosound",
                "--notv",
                "--seccomp",
                "--caps.drop=all"
            ] if os.name != 'nt' else []  # Disable Firejail on Windows
        }

    async def execute_code_streaming(self, websocket: WebSocket, code: str, user_id: str = "test_user") -> None:
        """Execute code with real-time streaming output via WebSocket"""
        try:
            # Security validation
            if not self._validate_code_security(code):
                await websocket.send_json({"error": "Code is blocked by security policy"})
                return

            # Normalization and preprocessing
            normalized_code = self.normalize_code(code)
            execution_id = self._generate_execution_id(user_id)

            # Configure platform-specific command
            if os.name == 'nt':  # Windows
                cmd = ["python", "-c", normalized_code]
                self.logging_utility.warning("Running without sandbox on Windows")
            else:  # Linux/MacOS
                cmd = [
                    "firejail",
                    *self.security_profile["firejail_args"],
                    "python3", "-c", normalized_code
                ]

            # Start async subprocess
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )

            self.active_processes[execution_id] = proc
            await self._stream_process_output(proc, websocket, execution_id)

        except Exception as e:
            self.logging_utility.error(f"Stream execution failed: {str(e)}")
            await websocket.send_json({
                "error": str(e),
                "code": normalized_code
            })


    async def _stream_process_output(self, proc, websocket, execution_id):
        """Stream output from process to WebSocket"""
        try:
            # Read output line-by-line
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break

                await websocket.send_text(line.decode().strip())
                self._log_execution_trace(execution_id, line.decode())

            # Send completion status
            return_code = await proc.wait()
            await websocket.send_json({
                "status": "complete",
                "exit_code": return_code,
                "execution_id": execution_id
            })

        except WebSocketDisconnect:
            self.logging_utility.warning(f"Client disconnected from execution {execution_id}")
            proc.terminate()
        finally:
            del self.active_processes[execution_id]
            await websocket.close()

    def _validate_code_security(self, code: str) -> bool:
        """Enhanced security validation"""
        blocked_patterns = [
            r"(__import__|exec|eval)\s*\(",
            r"(subprocess|os|sys)\.(system|popen)",
            r"open\s*\([^)]*[wac]\+",
            r"import\s+(os|sys|subprocess)"
        ]

        return not any(re.search(pattern, code) for pattern in blocked_patterns)

    def _generate_execution_id(self, user_id: str) -> str:
        return f"{user_id}-{int(time.time() * 1000)}"

    def _log_execution_trace(self, execution_id: str, output: str):
        """Structured logging for audit purposes"""
        self.logging_utility.info(json.dumps({
            "execution_id": execution_id,
            "timestamp": datetime.utcnow().isoformat(),
            "output": output.strip()
        }))


# Add this at the bottom of your file
# Replace the entire if __name__ == "__main__" block with:
if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI
    import asyncio
    import websockets
    from datetime import datetime

    # Minimal test server
    app = FastAPI()
    handler = StreamingCodeExecutionHandler()


    @app.websocket("/ws/execute")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        try:
            data = await websocket.receive_text()
            code = json.loads(data)["code"]
            await handler.execute_code_streaming(websocket, code)
        except json.JSONDecodeError:
            await websocket.close(code=1003)


    async def run_test():
        """Command line test without web UI"""
        test_code = """
import time, math
for i in range(3):
    print(f"Square root of {i} = {math.sqrt(i):.3f}")
    time.sleep(0.8)
        """.strip()

        async with websockets.connect("ws://localhost:4000/ws/execute") as ws:
            print("\nTESTING SECURE CODE EXECUTION STREAMING")
            print("Sending code:", test_code)
            await ws.send(json.dumps({"code": test_code}))

            try:
                while True:
                    msg = await asyncio.wait_for(ws.recv(), timeout=5)
                    print(f"RECEIVED: {msg}")
            except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosedOK):
                print("\nTEST COMPLETED")


    async def main():
        server = uvicorn.Server(
            config=uvicorn.Config(
                app,
                host="0.0.0.0",
                port=4000,
                log_level="info"
            )
        )

        await asyncio.gather(
            server.serve(),
            run_test()
        )


    asyncio.run(main())