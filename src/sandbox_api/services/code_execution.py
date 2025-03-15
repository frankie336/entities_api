import asyncio
import os
import re
import tempfile
import time

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect
from .logging_service import LoggingUtility


class StreamingCodeExecutionHandler:
    def __init__(self):
        self.logging_utility = LoggingUtility()
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
        self.required_imports = (
            "import asyncio\n"
            "import math\n"
            "import time\n"
            "from datetime import datetime\n"
        )

    def normalize_code(self, code: str) -> str:
        """Enhanced code normalization with indentation correction and line continuation handling."""
        # Phase 1: Basic sanitization
        replacements = {
            '“': '"', '”': '"', '‘': "'", '’': "'",
            '\u00b2': '**2', '^': '**',
            '⇒': '->',  # Unicode arrow to Python return type annotation
            '×': '*', '÷': '/',
        }
        for k, v in replacements.items():
            code = code.replace(k, v)

        # Remove non-ASCII characters except comments
        code = re.sub(r'[^\x00-\x7F]+', '', code)

        # Phase 2: Line continuation and indentation repair
        lines = []
        pending_continuation = False
        indent_size = 4  # Default Python indent

        for line in code.split('\n'):
            # Strip trailing whitespace and normalize line endings
            line = line.rstrip()

            # Detect broken line continuations
            continuation_operators = r'[+\-*/%=<>^|&@,{([:]\s*$'
            if re.search(continuation_operators, line):
                line = line.rstrip('\\').rstrip() + ' '
                pending_continuation = True
                lines.append(line)
                continue

            if pending_continuation:
                # Merge with previous line
                if lines:
                    lines[-1] += line.lstrip()
                else:
                    lines.append(line)
                pending_continuation = False
            else:
                lines.append(line)

        # Phase 3: Indentation correction
        code = []
        indent_level = 0
        for line in lines:
            line = line.expandtabs(4)

            # Strip empty lines
            if not line.strip():
                continue

            # Calculate current indentation
            stripped = line.lstrip()
            current_indent = len(line) - len(stripped)

            # Align to expected indent level
            expected_indent = indent_level * indent_size
            if current_indent < expected_indent:
                # Add missing indentation
                line = ' ' * expected_indent + stripped
            elif current_indent > expected_indent:
                # Reset to previous indent level
                line = ' ' * expected_indent + stripped

            # Update indent level
            if stripped.endswith(':'):
                indent_level += 1
            elif stripped.startswith(('return', 'pass', 'raise', 'break', 'continue')):
                indent_level = max(0, indent_level - 1)

            code.append(line)

        normalized_code = '\n'.join(code)

        # Phase 4: Wrap single expressions in print
        if re.match(r'^[\w\.]+\s*\(.*\)\s*$', normalized_code.strip()):
            normalized_code = f"print({normalized_code.strip()})"

        return self.required_imports + normalized_code

    async def execute_code_streaming(self, websocket: WebSocket, code: str, user_id: str = "test_user") -> None:
        """Executes code in a secured environment with real-time output streaming."""
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

