import ast
import asyncio
import os
import re
import shutil
import tempfile
import time
import traceback
from typing import Tuple

from dotenv import load_dotenv
from fastapi import WebSocket
from projectdavid import Entity
# Correct import for Sandbox context
from sandbox.services.logging_service import LoggingUtility
from starlette.websockets import WebSocketDisconnect

load_dotenv()


class StreamingCodeExecutionHandler:
    def __init__(self):
        self.logging_utility = LoggingUtility()
        self.active_processes = {}

        # ───────────────────────── DIRS ──────────────────────────
        self.root_dir = os.getcwd()
        self.generated_files_dir = os.path.abspath(
            os.path.join(self.root_dir, "generated_files")
        )
        # Keep MPL cache separate
        self.mpl_cache_dir = os.path.abspath(os.path.join(self.root_dir, "mpl_cache"))

        os.makedirs(self.generated_files_dir, exist_ok=True)
        os.makedirs(self.mpl_cache_dir, exist_ok=True)

        os.environ["MPLCONFIGDIR"] = self.mpl_cache_dir
        self.logging_utility.info("MPLCONFIGDIR set to: %s", self.mpl_cache_dir)
        self.last_executed_script_path = None

        # ───────────────────────── FIREJAIL ──────────────────────
        disable_firejail = os.getenv("DISABLE_FIREJAIL", "false").lower() == "true"
        self.security_profile = {
            "firejail_args": (
                []
                if os.name == "nt" or disable_firejail
                else [
                    f"--private={self.generated_files_dir}",
                    "--noprofile",
                    "--nogroups",
                    "--nosound",
                    "--notv",
                    "--seccomp",
                    "--caps.drop=all",
                    "--net",
                    "--env=PYTHONPATH",
                ]
            )
        }
        self.required_imports = (
            "import asyncio\nimport math\nimport time\nfrom datetime import datetime\n"
        )

    def normalize_code(self, code: str) -> str:
        """
        Normalizes code (smart quotes, indentation fixes).
        """
        replacements = {
            '"': '"',
            "“": "'",
            "”": "'",
            "\u00b2": "**2",
            "^": "**",
            "⇒": "->",
            "×": "*",
            "÷": "/",
        }
        for k, v in replacements.items():
            code = code.replace(k, v)
        code = re.sub(r"[^\x00-\x7F]+", "", code)

        lines, pending = [], False
        indent_size = 4

        for line in code.split("\n"):
            line = line.rstrip()
            if re.search(r"[+\-*/%=<>^|&@,{([:]\s*$", line):
                line = line.rstrip("\\").rstrip() + " "
                pending = True
                lines.append(line)
                continue
            if pending:
                lines[-1] += line.lstrip() if lines else line
                pending = False
            else:
                lines.append(line)

        formatted_lines, indent_level, block_started = [], 0, False
        for i, line in enumerate(lines):
            stripped = line.lstrip()
            if not stripped:
                formatted_lines.append("")
                continue
            current_indent = len(line) - len(stripped)
            if i > 0 and block_started and current_indent > 0:
                block_started, indent_size = False, current_indent
            expected_indent = indent_level * indent_size
            if stripped.endswith(":"):
                formatted_line = " " * expected_indent + stripped
                indent_level += 1
                block_started = True
            elif stripped.startswith(("return", "pass", "raise", "break", "continue")):
                if indent_level > 0:
                    indent_level -= 1
                formatted_line = " " * (indent_level * indent_size) + stripped
            else:
                formatted_line = " " * expected_indent + stripped
            formatted_lines.append(formatted_line)

        final_lines, i = [], 0
        while i < len(formatted_lines):
            line = formatted_lines[i]
            stripped = line.lstrip()
            if stripped.endswith(":"):
                if i + 1 < len(formatted_lines) and not formatted_lines[i + 1].strip():
                    final_lines.append(line)
                    final_lines.append("")
                    i += 2
                    continue
                if i + 1 < len(formatted_lines):
                    next_line = formatted_lines[i + 1]
                    next_stripped = next_line.lstrip()
                    if (len(next_line) - len(next_stripped)) <= (
                        len(line) - len(stripped)
                    ) and next_stripped:
                        final_lines.append(line)
                        final_lines.append(
                            " " * (len(line) - len(stripped) + indent_size) + "pass"
                        )
                    else:
                        final_lines.append(line)
                else:
                    final_lines.append(line)
                    final_lines.append(
                        " " * (len(line) - len(stripped) + indent_size) + "pass"
                    )
            else:
                final_lines.append(line)
            i += 1

        normalized_code = "\n".join(final_lines)
        if re.match(r"^[\w\.]+\s*\(.*\)\s*$", normalized_code.strip()):
            normalized_code = f"print({normalized_code.strip()})"
        return self.required_imports + self._ast_validate_and_fix(normalized_code)

    def _ast_validate_and_fix(self, code: str) -> str:
        try:
            ast.parse(code)
            return code
        except SyntaxError as e:
            fixed_code, success = self._fix_common_syntax_errors(code, e)
            return fixed_code if success else code

    def _fix_common_syntax_errors(
        self, code: str, error: SyntaxError
    ) -> Tuple[str, bool]:
        lines = code.split("\n")
        line_number = error.lineno - 1
        if line_number >= len(lines) or line_number < 0:
            return code, False
        prob_line, error_msg = lines[line_number], error.msg.lower()
        if "indentation" in error_msg:
            if "expected an indented block" in error_msg:
                lines[line_number] = (
                    " " * (len(prob_line) - len(prob_line.lstrip()) + 4)
                    + prob_line.lstrip()
                )
                return "\n".join(lines), True
            elif "unexpected indent" in error_msg:
                prev_line = lines[line_number - 1] if line_number > 0 else ""
                lines[line_number] = (
                    " " * (len(prev_line) - len(prev_line.lstrip()))
                    + prob_line.lstrip()
                )
                return "\n".join(lines), True
        elif "parentheses" in error_msg and "(" in prob_line:
            lines[line_number] = prob_line + ")"
            return "\n".join(lines), True
        elif "expected" in error_msg and ":" in error_msg:
            if any(
                k in prob_line for k in ["if", "for", "while", "def", "class"]
            ) and not prob_line.rstrip().endswith(":"):
                lines[line_number] = prob_line.rstrip() + ":"
                return "\n".join(lines), True
        return code, False

    async def execute_code_streaming(
        self, websocket: WebSocket, code: str, user_id: str = "test_user"
    ) -> None:
        tmp_path = None
        try:
            full_code = self.normalize_code(code)
            try:
                ast.parse(full_code)
            except SyntaxError as e:
                await websocket.send_json(
                    {
                        "error": f"Syntax Error: {''.join(traceback.format_exception_only(type(e), e))}"
                    }
                )
                return

            if not self._validate_code_security(full_code):
                await websocket.send_json({"error": "Security violation"})
                return

            execution_id = f"{user_id}-{int(time.time() * 1000)}"
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, dir=self.generated_files_dir
            ) as tmp:
                tmp.write(full_code)
                tmp_path = tmp.name

            self.last_executed_script_path = tmp_path

            cmd = (
                ["python3", "-u", tmp_path]
                if (os.name == "nt" or os.getenv("DISABLE_FIREJAIL") == "true")
                else [
                    "firejail",
                    *self.security_profile["firejail_args"],
                    "python3",
                    "-u",
                    tmp_path,
                ]
            )

            # [FIX] Force CWD to generated_files_dir so plot.savefig() lands in the right place
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=self.generated_files_dir,  # <--- THE FIX
            )
            self.active_processes[execution_id] = proc
            await self._stream_process_output(proc, websocket, execution_id)

            uploaded_files = await self._upload_generated_files(user_id=user_id)

            # [DEBUG] Log upload count
            if uploaded_files:
                self.logging_utility.info(
                    f"Uploading {len(uploaded_files)} files: {uploaded_files}"
                )
            else:
                self.logging_utility.warning("No generated files found to upload.")

            await websocket.send_json(
                {
                    "status": "complete",
                    "execution_id": execution_id,
                    "uploaded_files": uploaded_files,
                }
            )
        except Exception as e:
            self.logging_utility.error("Execution failed: %s", str(e))
            try:
                await websocket.send_json({"error": str(e)})
            except:
                pass
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
            self.last_executed_script_path = None
            try:
                await websocket.close()
            except:
                pass

    async def _stream_process_output(
        self, proc, websocket: WebSocket, execution_id: str
    ) -> None:
        try:
            while True:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=30)
                if not line:
                    break
                await websocket.send_text(line.decode(errors="replace"))
            await websocket.send_json(
                {
                    "status": "process_complete",
                    "exit_code": await proc.wait(),
                    "execution_id": execution_id,
                }
            )
        except Exception as e:
            self.logging_utility.error("Stream error: %s", str(e))
            proc.terminate()
        finally:
            self.active_processes.pop(execution_id, None)

    def _validate_code_security(self, code: str) -> bool:
        blocked = [
            r"(__import__|exec|eval|input)\s*\(",
            r"(subprocess|os|sys)\.(system|popen|run|exec)",
            r"asyncio\.(create_subprocess|run_in_executor)",
            r"import\s+(os|sys|ctypes)",
        ]
        return not any(re.search(p, code) for p in blocked)

    async def _upload_generated_files(self, user_id: str) -> list:
        uploaded_files = []
        client = Entity(
            api_key=os.getenv("ADMIN_API_KEY"),
            base_url="http://fastapi_cosmic_catalyst:9000",
        )

        async def upload_single_file(filename, file_path):
            if os.path.isdir(file_path):
                return None
            try:
                upload = client.files.upload_file(
                    file_path=file_path, purpose="assistants"
                )
                return {
                    "filename": filename,
                    "id": upload.id,
                    "url": client.files.get_signed_url(
                        upload.id, use_real_filename=True
                    ),
                }
            except Exception as e:
                self.logging_utility.error("Upload failed for %s: %s", filename, str(e))
                return None

        # Build tasks
        tasks = []
        # Check if dir exists first
        if os.path.exists(self.generated_files_dir):
            for fname in os.listdir(self.generated_files_dir):
                fpath = os.path.join(self.generated_files_dir, fname)

                # Skip the script that is currently running
                if self.last_executed_script_path and os.path.exists(
                    self.last_executed_script_path
                ):
                    if os.path.samefile(fpath, self.last_executed_script_path):
                        continue

                if os.path.isfile(fpath):
                    tasks.append(upload_single_file(fname, fpath))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, dict):
                    uploaded_files.append(res)

        # Cleanup
        if os.path.exists(self.generated_files_dir):
            for fname in os.listdir(self.generated_files_dir):
                fpath = os.path.join(self.generated_files_dir, fname)
                try:
                    if os.path.isfile(fpath) or os.path.islink(fpath):
                        os.remove(fpath)
                    elif os.path.isdir(fpath):
                        shutil.rmtree(fpath)
                except Exception as e:
                    self.logging_utility.error(
                        "Cleanup failed for %s: %s", fname, str(e)
                    )

        return uploaded_files
