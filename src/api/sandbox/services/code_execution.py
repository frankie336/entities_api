import asyncio
import os
import re
import tempfile
import time

from dotenv import load_dotenv
from entities_common import EntitiesInternalInterface
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from sandbox.services.logging_service import LoggingUtility

load_dotenv()

class StreamingCodeExecutionHandler:
    def __init__(self):
        self.logging_utility = LoggingUtility()
        self.active_processes = {}
        self.generated_files_dir = os.path.abspath("generated_files")
        os.makedirs(self.generated_files_dir, exist_ok=True)
        self.last_executed_script_path = None

        self.logging_utility.info("Current working directory: %s", os.getcwd())
        self.logging_utility.info("Generated files directory: %s", self.generated_files_dir)

        disable_firejail = os.getenv("DISABLE_FIREJAIL", "false").lower() == "true"
        self.security_profile = {
            "firejail_args": [] if os.name == 'nt' or disable_firejail else [
                f"--private={self.generated_files_dir}",
                "--noprofile", "--nogroups", "--nosound", "--notv",
                "--seccomp", "--caps.drop=all", "--net", "--env=PYTHONPATH"
            ]
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
            '⇒': '->', '×': '*', '÷': '/',
        }
        for k, v in replacements.items():
            code = code.replace(k, v)
        code = re.sub(r'[^\x00-\x7F]+', '', code)

        lines, pending = [], False
        indent_size = 4
        for line in code.split('\n'):
            line = line.rstrip()
            if re.search(r'[+\-*/%=<>^|&@,{([:]\s*$', line):
                line = line.rstrip('\\').rstrip() + ' '
                pending = True
                lines.append(line)
                continue
            if pending:
                lines[-1] += line.lstrip() if lines else line
                pending = False
            else:
                lines.append(line)

        formatted_lines, indent_level = [], 0
        for line in lines:
            line = line.expandtabs(indent_size)
            stripped = line.lstrip()
            expected_indent = indent_level * indent_size
            if (curr := len(line) - len(stripped)) != expected_indent:
                line = ' ' * expected_indent + stripped
            if stripped.endswith(':'):
                indent_level += 1
            elif stripped.startswith(('return', 'pass', 'raise', 'break', 'continue')):
                indent_level = max(0, indent_level - 1)
            formatted_lines.append(line)

        normalized_code = '\n'.join(formatted_lines)
        if re.match(r'^[\w\.]+\s*\(.*\)\s*$', normalized_code.strip()):
            normalized_code = f"print({normalized_code.strip()})"

        return self.required_imports + normalized_code

    async def execute_code_streaming(self, websocket: WebSocket, code: str, user_id: str = "test_user") -> None:
        tmp_path = None
        try:
            full_code = self.normalize_code(code)
            if not self._validate_code_security(full_code):
                await websocket.send_json({"error": "Code violates security policy"})
                self.logging_utility.warning("Security validation failed for user %s", user_id)
                return

            execution_id = f"{user_id}-{int(time.time() * 1000)}"

            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, dir=self.generated_files_dir) as tmp:
                tmp.write(full_code)
                tmp_path = tmp.name

            self.last_executed_script_path = tmp_path
            self.logging_utility.info("Normalized code written to: %s", tmp_path)

            disable_firejail = os.getenv("DISABLE_FIREJAIL", "false").lower() == "true"
            cmd = (
                ["python3", "-u", tmp_path] if os.name == 'nt' or disable_firejail else
                ["firejail", *self.security_profile["firejail_args"], "python3", "-u", tmp_path]
            )

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=None if os.name != 'nt' and not disable_firejail else self.generated_files_dir
            )
            self.active_processes[execution_id] = proc
            await self._stream_process_output(proc, websocket, execution_id)

            uploaded_files = await self._upload_generated_files(user_id=user_id)
            await websocket.send_json({
                "status": "complete",
                "execution_id": execution_id,
                "uploaded_files": uploaded_files
            })

        except Exception as e:
            self.logging_utility.error("Execution failed: %s", str(e))
            try:
                await websocket.send_json({"error": str(e)})
            except Exception:
                pass
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
            self.last_executed_script_path = None
            try:
                await websocket.close()
            except RuntimeError:
                self.logging_utility.debug("WebSocket already closed.")

    async def _stream_process_output(self, proc, websocket: WebSocket, execution_id: str) -> None:
        try:
            while True:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=30)
                if not line:
                    break
                await websocket.send_text(line.decode(errors='replace'))

            return_code = await proc.wait()
            await websocket.send_json({
                "status": "process_complete",
                "exit_code": return_code,
                "execution_id": execution_id
            })
        except asyncio.TimeoutError:
            self.logging_utility.error("Timeout occurred for execution_id: %s", execution_id)
            proc.terminate()
            await websocket.send_json({"error": "Execution timed out."})
        except WebSocketDisconnect:
            self.logging_utility.warning("Client disconnected: %s", execution_id)
            proc.terminate()
        except Exception as e:
            self.logging_utility.error("Stream error: %s", str(e))
        finally:
            self.active_processes.pop(execution_id, None)

    def _validate_code_security(self, code: str) -> bool:
        blocked_patterns = [
            r"(__import__|exec|eval|compile|input)\s*\(",
            r"(subprocess|os|sys)\.(system|popen|run|exec)",
            r"asyncio\.(create_subprocess|run_in_executor)",
            r"loop\.(add_reader|set_default_executor)",
            r"import\s+(os|sys|ctypes)",
            r"os\.(environ|chdir|chmod|remove|unlink|rmdir)",
        ]
        return not any(re.search(p, code) for p in blocked_patterns)

    async def _upload_generated_files(self, user_id: str) -> list:
        uploaded_files = []
        client = EntitiesInternalInterface(base_url="http://fastapi_cosmic_catalyst:9000")


        try:
            user = client.users.create_user(name="test_user")
        except Exception as e:
            self.logging_utility.error("Failed to create user: %s", str(e))
            return uploaded_files

        async def upload_single_file(filename, file_path):
            try:
                upload = client.files.upload_file(file_path=file_path, user_id=user.id, purpose="assistants")

                file_url = client.files.get_signed_url(upload.id, label=filename, markdown=True, use_real_filename=True)

                return {"filename": filename, "id": upload.id, "url": file_url}
            except Exception as e:
                self.logging_utility.error("Upload failed for %s: %s", filename, str(e))
                return None

        tasks = [
            upload_single_file(fname, os.path.join(self.generated_files_dir, fname))
            for fname in os.listdir(self.generated_files_dir)
            if os.path.isfile(os.path.join(self.generated_files_dir, fname))
            and not self.last_executed_script_path or not os.path.samefile(
                os.path.join(self.generated_files_dir, fname), self.last_executed_script_path
            )
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if isinstance(res, dict):
                uploaded_files.append(res)

        for fname in os.listdir(self.generated_files_dir):
            try:
                os.remove(os.path.join(self.generated_files_dir, fname))
            except Exception as e:
                self.logging_utility.error("Cleanup failed for %s: %s", fname, str(e))

        return uploaded_files
