import asyncio
import hashlib
import hmac
import os
import re
import tempfile
import time
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect
from entities_common import EntitiesInternalInterface


#print(EntitiesInternalInterface())
#client = EntitiesInternalInterface()
#user = client.users.create_user(name="test user")
#print(user.id)
#time.sleep(100)




from sandbox.services.logging_service import LoggingUtility




class StreamingCodeExecutionHandler:
    def __init__(self):
        self.logging_utility = LoggingUtility()
        self.active_processes = {}
        self.generated_files_dir = os.path.abspath("generated_files")
        os.makedirs(self.generated_files_dir, exist_ok=True)

        self.security_profile = {
            "firejail_args": [
                "--noprofile",
                f"--whitelist={self.generated_files_dir}",
                f"--chdir={self.generated_files_dir}",  # Critical fix
                "--nogroups",
                "--nosound",
                "--notv",
                "--seccomp",
                "--caps.drop=all",
                #--------------------------------
                # !!four outside communication!!
                #-------------------------------
                "--net",  # Allow network access for uploads
                "--env=PYTHONPATH",

            ] if os.name != 'nt' else []
        }
        self.required_imports = (
            "import asyncio\n"
            "import math\n"
            "import time\n"
            "from datetime import datetime\n"
        )

    def normalize_code(self, code: str) -> str:
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
            if re.search(r'[+\-*/%=<>^|&@,{([:]\s*$', line):
                line = line.rstrip('\\').rstrip() + ' '
                pending_continuation = True
                lines.append(line)
                continue
            if pending_continuation:
                lines[-1] += line.lstrip() if lines else line
                pending_continuation = False
            else:
                lines.append(line)
        code_lines = []
        indent_level = 0
        for line in lines:
            line = line.expandtabs(4)
            stripped = line.lstrip()
            current_indent = len(line) - len(stripped)
            expected_indent = indent_level * indent_size
            if current_indent != expected_indent:
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

            # Create temp file INSIDE generated_files_dir
            with tempfile.NamedTemporaryFile(
                    mode='w',
                    suffix='.py',
                    delete=False,
                    dir=self.generated_files_dir  # Critical fix
            ) as tmp:
                tmp.write(full_code)
                tmp_path = tmp.name

            self.logging_utility.info("Normalized code written to: %s", tmp_path)

            if os.name == 'nt':
                cmd = ["python", tmp_path]
                cwd = self.generated_files_dir
            else:
                cmd = [
                    "firejail",
                    *self.security_profile["firejail_args"],
                    "python3", "-u", tmp_path
                ]
                cwd = None

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd
            )
            self.active_processes[execution_id] = proc
            await self._stream_process_output(proc, websocket, execution_id)

            uploaded_files = await self._upload_generated_files()
            await websocket.send_json({
                "status": "complete",
                "execution_id": execution_id,
                "uploaded_files": uploaded_files
            })

        except Exception as e:
            self.logging_utility.error("Execution failed: %s", str(e))
            await websocket.send_json({"error": str(e)})
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
            await websocket.close()

    async def _stream_process_output(self, proc, websocket, execution_id):
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                await websocket.send_text(line.decode())

            return_code = await proc.wait()
            await websocket.send_json({
                "status": "process_complete",
                "exit_code": return_code,
                "execution_id": execution_id
            })
        except WebSocketDisconnect:
            self.logging_utility.warning("Client disconnected: %s", execution_id)
            proc.terminate()
        except Exception as e:
            self.logging_utility.error("Stream error: %s", str(e))
        finally:
            self.active_processes.pop(execution_id, None)

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
        uploaded_urls = []
        self.logging_utility.debug("Scanning directory: %s", self.generated_files_dir)

        for filename in os.listdir(self.generated_files_dir):
            file_path = os.path.join(self.generated_files_dir, filename)
            if not os.path.isfile(file_path):
                continue

            try:
                client = EntitiesInternalInterface()
                upload = client.files.upload_file(
                    file_path=file_path,
                    user_id="user_fD3oruiyNMu4ycAvcZgzRI",
                    purpose="assistants"
                )

                expires = int(time.time()) + 600
                secret_key = os.getenv("DEFAULT_SECRET_KEY", "default_secret_key")
                data = f"{upload.id}:{expires}"
                signature = hmac.new(secret_key.encode(), data.encode(), hashlib.sha256).hexdigest()
                file_url = f"http://samba_server/cosmic_share/{upload.id}?sig={signature}&expires={expires}"
                uploaded_urls.append(file_url)
                self.logging_utility.info("Uploaded %s", filename)


            except Exception as e:
                self.logging_utility.error("Upload failed for %s: %s", filename, str(e))
            finally:
                try:
                    os.remove(file_path)
                    self.logging_utility.debug("Cleaned up %s", filename)
                except Exception as e:
                    self.logging_utility.error("Cleanup failed for %s: %s", filename, str(e))

        self.logging_utility.debug("Found %d files to upload", len(uploaded_urls))
        return uploaded_urls