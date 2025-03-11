import asyncio
import os
import re
import tempfile
import time

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect
from entities_api.platform_tools.code_interpreter.code_interpreter_service import CodeExecutionService

class StreamingCodeExecutionHandler(CodeExecutionService):
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
            ] if os.name != 'nt' else []
        }

    async def execute_code_streaming(self, websocket: WebSocket, code: str, user_id: str = "test_user") -> None:
        """Executes code in a secured environment with real-time output streaming.

        Args:
            websocket: Active WebSocket connection for output streaming
            code: Untrusted user-submitted Python code
            user_id: Identifier for audit logging and process tracking

        Workflow:
        1. Normalizes input code (unicode cleanup, security padding)
        2. Validates against security patterns
        3. Creates temporary execution artifact
        4. Spawns sandboxed Python process
        5. Streams output with typing simulation
        6. Performs automatic cleanup

        Raises:
            WebSocketDisconnect: On client-initiated termination
            RuntimeError: If security validation fails
        """
        tmp_path = None
        try:
            full_code = self.normalize_code(code)
            if not self._validate_code_security(full_code):
                await websocket.send_json({"error": "Code violates security policy"})
                return

            execution_id = f"{user_id}-{int(time.time() * 1000)}"

            # Write the normalized code to a temporary file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as tmp:
                tmp.write(full_code)
                tmp.flush()
                tmp_path = tmp.name

            # Read back and log the temporary file content for debugging
            with open(tmp_path, 'r') as f:
                file_content = f.read()
            self.logging_utility.info("Normalized code written to temp file (%s):\n%s", tmp_path, file_content)

            # Build the command to execute the temporary file in unbuffered mode
            if os.name == 'nt':
                cmd = ["python", tmp_path]
            else:
                cmd = [
                    "firejail",
                    *self.security_profile["firejail_args"],
                    "python3", "-u", tmp_path
                ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )
            self.active_processes[execution_id] = proc
            await self._stream_process_output(proc, websocket, execution_id)
        except Exception as e:
            self.logging_utility.error("Stream execution failed: %s", str(e))
            await websocket.send_json({"error": str(e), "code": code})
        finally:
            # Auto cleanup of the temporary file
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                    self.logging_utility.info("Temporary file %s removed.", tmp_path)
                except Exception as e:
                    self.logging_utility.error("Failed to remove temporary file %s: %s", tmp_path, e)

    async def _stream_process_output(self, proc, websocket, execution_id):
        try:
            while True:
                # Read one full line from the process output
                line = await proc.stdout.readline()
                if not line:
                    break
                try:
                    # Send the entire line over the WebSocket
                    await websocket.send_text(line.decode())
                    # Optionally, if you still want a typing simulation, iterate over characters:
                    # for ch in line.decode():
                    #     await websocket.send_text(ch)
                    #     await asyncio.sleep(0.05)
                except WebSocketDisconnect:
                    self.logging_utility.warning("Client disconnected from execution %s", execution_id)
                    proc.terminate()
                    break
            return_code = await proc.wait()
            await websocket.send_json({
                "status": "complete",
                "exit_code": return_code,
                "execution_id": execution_id
            })
        except Exception as e:
            self.logging_utility.error("Error in execution stream: %s", str(e))
            proc.terminate()
        finally:
            self.active_processes.pop(execution_id, None)
            await websocket.close()

    def _validate_code_security(self, code: str) -> bool:
        blocked_patterns = [
            r"(__import__|exec|eval)\s*\(",
            r"(subprocess|os|sys)\.(system|popen|run)",
            r"open\s*\([^)]*[wac]\+",
            r"asyncio\.(create_subprocess|run_in_executor)",
            r"loop\.(add_reader|set_default_executor)",
            r"import\s+os\s*,\s*sys",
            r"import\s+ctypes",
            r"os\.(environ|chdir|chmod)"
        ]
        return not any(re.search(pattern, code) for pattern in blocked_patterns)


