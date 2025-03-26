import asyncio
import os
import re
import tempfile
import time
import json
import hmac
import hashlib
import shutil

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect
from .logging_service import LoggingUtility
from common.clients.client import EntitiesInternalInterface


class StreamingCodeExecutionHandler:
    def __init__(self):
        self.logging_utility = LoggingUtility()
        self.active_processes = {}
        # Firejail arguments for non-Windows; note that we now include the --private option.
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
        # Known directory to capture all generated files.
        self.generated_files_dir = os.path.abspath("generated_files")
        os.makedirs(self.generated_files_dir, exist_ok=True)

    def normalize_code(self, code: str) -> str:
        """Enhanced code normalization with indentation correction and line continuation handling."""
        replacements = {
            '“': '"', '”': '"', '‘': "'", '’': "'",
            '\u00b2': '**2', '^': '**',
            '⇒': '->',
            '×': '*', '÷': '/',
        }
        for k, v in replacements.items():
            code = code.replace(k, v)
        code = re.sub(r'[^\x00-\x7F]+', '', code)
        lines = []
        pending_continuation = False
        indent_size = 4
        for line in code.split('\n'):
            line = line.rstrip()
            continuation_operators = r'[+\-*/%=<>^|&@,{([:]\s*$'
            if re.search(continuation_operators, line):
                line = line.rstrip('\\').rstrip() + ' '
                pending_continuation = True
                lines.append(line)
                continue
            if pending_continuation:
                if lines:
                    lines[-1] += line.lstrip()
                else:
                    lines.append(line)
                pending_continuation = False
            else:
                lines.append(line)
        code_lines = []
        indent_level = 0
        for line in lines:
            line = line.expandtabs(4)
            if not line.strip():
                continue
            stripped = line.lstrip()
            current_indent = len(line) - len(stripped)
            expected_indent = indent_level * indent_size
            if current_indent < expected_indent:
                line = ' ' * expected_indent + stripped
            elif current_indent > expected_indent:
                line = ' ' * expected_indent + stripped
            if stripped.endswith(':'):
                indent_level += 1
            elif stripped.startswith(('return', 'pass', 'raise', 'break', 'continue')):
                indent_level = max(0, indent_level - 1)
            code_lines.append(line)
        normalized_code = '\n'.join(code_lines)
        if re.match(r'^[\w\.]+\s*\(.*\)\s*$', normalized_code.strip()):
            normalized_code = f"print({normalized_code.strip()})"
        return self.required_imports + normalized_code

    async def execute_code_streaming(self, websocket: WebSocket, code: str, user_id: str = "test_user") -> None:
        tmp_path = None
        try:
            full_code = self.normalize_code(code)
            if not self._validate_code_security(full_code):
                await websocket.send_json({"error": "Code violates security policy"})
                return

            execution_id = f"{user_id}-{int(time.time() * 1000)}"
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as tmp:
                tmp.write(full_code)
                tmp.flush()
                tmp_path = tmp.name

            with open(tmp_path, 'r') as f:
                file_content = f.read()
            self.logging_utility.info("Normalized code written to temp file (%s):\n%s", tmp_path, file_content)

            if os.name == 'nt':
                # For Windows, we only set the working directory.
                cmd = ["python", tmp_path]
                cwd = self.generated_files_dir
            else:
                # For Unix-like systems, force the private filesystem view to the known directory.
                cmd = [
                    "firejail",
                    "--private=" + self.generated_files_dir,
                    *self.security_profile["firejail_args"],
                    "python3", "-u", tmp_path
                ]
                cwd = None  # Firejail will handle the filesystem isolation.

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd  # Ensure relative paths are resolved to our directory (for Windows).
            )
            self.active_processes[execution_id] = proc
            await self._stream_process_output(proc, websocket, execution_id)

            # After execution, process any generated files.
            uploaded_files = await self._upload_generated_files()

            # Return the final response with any file URLs.
            await websocket.send_json({
                "status": "complete",
                "execution_id": execution_id,
                "uploaded_files": uploaded_files
            })
        except Exception as e:
            self.logging_utility.error("Stream execution failed: %s", str(e))
            await websocket.send_json({"error": str(e), "code": code})
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                    self.logging_utility.info("Temporary file %s removed.", tmp_path)
                except Exception as e:
                    self.logging_utility.error("Failed to remove temporary file %s: %s", tmp_path, e)

    async def _stream_process_output(self, proc, websocket, execution_id):
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                try:
                    await websocket.send_text(line.decode())
                except WebSocketDisconnect:
                    self.logging_utility.warning("Client disconnected from execution %s", execution_id)
                    proc.terminate()
                    break
            return_code = await proc.wait()
            await websocket.send_json({
                "status": "process_complete",
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

    async def _upload_generated_files(self) -> list:
        """
        Checks the generated_files_dir for any files produced during execution,
        uploads each to the Samba server, generates a signed URL, and cleans up the file.
        Returns a list of signed URLs.
        """
        uploaded_urls = []
        for filename in os.listdir(self.generated_files_dir):
            file_path = os.path.join(self.generated_files_dir, filename)
            if os.path.isfile(file_path):
                try:
                    client = EntitiesInternalInterface()
                    upload = client.files.upload_file(
                        file_path=file_path,
                        user_id="default",
                        purpose="assistants"
                    )
                    expires = int(time.time()) + 600  # Valid for 10 minutes.
                    secret_key = os.getenv("DEFAULT_SECRET_KEY", "default_secret_key")
                    data = f"{upload.id}:{expires}"
                    url_signature = hmac.new(secret_key.encode(), data.encode(), hashlib.sha256).hexdigest()
                    file_url = f"http://samba_server/cosmic_share/{upload.id}?sig={url_signature}&expires={expires}"
                    self.logging_utility.info("File %s uploaded. Signed URL: %s", filename, file_url)
                    uploaded_urls.append(file_url)
                except Exception as e:
                    self.logging_utility.error("Error uploading file %s: %s", filename, e)
                finally:
                    try:
                        os.remove(file_path)
                        self.logging_utility.info("Generated file %s removed after upload.", filename)
                    except Exception as cleanup_err:
                        self.logging_utility.error("Failed to remove generated file %s: %s", filename, cleanup_err)
        return uploaded_urls
