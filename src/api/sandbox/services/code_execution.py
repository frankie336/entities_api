import ast
import asyncio
import os
import re
import tempfile
import time
import traceback
from typing import List, Tuple

from dotenv import load_dotenv
from fastapi import WebSocket
from projectdavid import Entity  # Assuming synchronous
from sandbox.services.logging_service import LoggingUtility
from starlette.websockets import WebSocketDisconnect

load_dotenv()


class StreamingCodeExecutionHandler:
    def __init__(self):
        self.logging_utility = LoggingUtility()
        self.active_processes = {}
        # --- Directory Setup ---
        self.base_generated_files_dir = os.path.abspath("generated_files")
        os.makedirs(self.base_generated_files_dir, exist_ok=True)
        self.mpl_cache_dir_host_path = os.path.join(
            self.base_generated_files_dir, ".matplotlib_cache"
        )
        os.makedirs(self.mpl_cache_dir_host_path, exist_ok=True)
        self.mpl_cache_dir_sandbox_path = ".matplotlib_cache"

        self.last_executed_script_path = None
        self.current_execution_dir = None

        self.logging_utility.info("Current working directory: %s", os.getcwd())
        self.logging_utility.info(
            "Base Generated files directory: %s", self.base_generated_files_dir
        )
        self.logging_utility.info(
            "Matplotlib cache directory (host): %s", self.mpl_cache_dir_host_path
        )

        disable_firejail = os.getenv("DISABLE_FIREJAIL", "false").lower() == "true"
        self.security_profile = {
            "firejail_args": (
                []
                if os.name == "nt" or disable_firejail
                else [
                    f"--private={self.base_generated_files_dir}",
                    f"--env=MPLCONFIGDIR={self.mpl_cache_dir_sandbox_path}",
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
            "import asyncio\n"
            "import math\n"
            "import time\n"
            "from datetime import datetime\n"
        )

    # --- normalize_code (No changes) ---
    def normalize_code(self, code: str) -> str:
        # Fix curly quotes and other special characters
        replacements = {
            '"': '"',
            "“": '"',
            "”": '"',  # Added common curly quotes
            "‘": "'",
            "’": "'",
            "\u00b2": "**2",
            "^": "**",
            "⇒": "->",
            "×": "*",
            "÷": "/",
        }
        for k, v in replacements.items():
            code = code.replace(k, v)
        # Remove non-ASCII chars that might cause issues if not handled properly later
        # Consider allowing specific unicode ranges if needed, but simple removal is safer
        code = re.sub(r"[^\x00-\x7F]+", "", code)

        # Handle line continuations and join continued lines (Basic version)
        # More robust parsing might be needed for complex cases
        processed_lines = []
        buffer = ""
        for line in code.splitlines():
            stripped_line = line.strip()
            if buffer:
                buffer += stripped_line
                if not stripped_line.endswith("\\"):
                    processed_lines.append(buffer)
                    buffer = ""
            elif stripped_line.endswith("\\"):
                buffer += stripped_line.rstrip("\\").rstrip() + " "
            else:
                processed_lines.append(line)  # Keep original spacing if not continued

        code = "\n".join(processed_lines)

        # Fix up indentation (Simplified heuristic version)
        lines = code.splitlines()
        formatted_lines = []
        current_indent = 0
        indent_size = 4  # Assume 4 spaces

        for line in lines:
            stripped = line.lstrip()
            if not stripped:  # Keep empty lines as they are
                formatted_lines.append("")
                continue

            # Calculate indent based on common keywords
            # Note: This is a very basic heuristic and won't handle all cases correctly.
            # Proper indentation fixing often requires AST analysis.
            indent_change = 0
            if stripped.endswith(":"):
                formatted_lines.append(" " * current_indent + stripped)
                current_indent += indent_size
            # Basic check for dedent keywords - might dedent too early
            elif stripped.startswith(
                ("return", "pass", "raise", "break", "continue", "elif", "else")
            ):
                current_indent = max(0, current_indent - indent_size)
                formatted_lines.append(" " * current_indent + stripped)
            else:
                # Check if current line's physical indent suggests a dedent
                physical_indent = len(line) - len(stripped)
                if physical_indent < current_indent:
                    current_indent = physical_indent  # Align with actual indent if less
                formatted_lines.append(" " * current_indent + stripped)

        # Add pass to empty blocks (simple check)
        final_lines = []
        for i, line in enumerate(formatted_lines):
            final_lines.append(line)
            stripped = line.strip()
            if stripped.endswith(":"):
                # Check if next line exists and is empty or less indented
                if (
                    i + 1 >= len(formatted_lines)
                    or not formatted_lines[i + 1].strip()
                    or (
                        len(formatted_lines[i + 1])
                        - len(formatted_lines[i + 1].lstrip())
                    )
                    <= (len(line) - len(stripped))
                ):
                    final_lines.append(
                        " " * (len(line) - len(stripped) + indent_size) + "pass"
                    )

        normalized_code = "\n".join(final_lines)

        # Handle single expression wrapping (Keep previous logic)
        trimmed_norm_code = normalized_code.strip()
        if (
            "\n" not in trimmed_norm_code
            and trimmed_norm_code
            and not trimmed_norm_code.startswith("print(")
            and "=" not in trimmed_norm_code
        ):
            if re.match(r"^[\w\.]+(\s*\(.*\))?$", trimmed_norm_code):
                normalized_code = f"print({trimmed_norm_code})"

        # AST validation and error correction
        normalized_code = self._ast_validate_and_fix(normalized_code)

        return self.required_imports + "\n" + normalized_code

    # --- _ast_validate_and_fix (No changes) ---
    def _ast_validate_and_fix(self, code: str) -> str:
        try:
            ast.parse(code)
            return code
        except SyntaxError as e:
            self.logging_utility.warning(
                "AST validation failed: %s at line %s, offset %s, text: %s",
                e.msg,
                e.lineno,
                e.offset,
                e.text,
            )
            fixed_code, success = self._fix_common_syntax_errors(code, e)
            if success:
                self.logging_utility.info("Attempted fix for syntax error")
                try:
                    ast.parse(fixed_code)
                    self.logging_utility.info("Syntax fix validated successfully.")
                    return fixed_code
                except SyntaxError as e2:
                    self.logging_utility.warning(
                        "Syntax fix failed validation: %s", e2.msg
                    )
                    return code  # Revert if fix is invalid
            return code

    # --- _fix_common_syntax_errors (No changes, keep previous version) ---
    def _fix_common_syntax_errors(
        self, code: str, error: SyntaxError
    ) -> Tuple[str, bool]:
        lines = code.split("\n")
        import_lines_count = self.required_imports.count("\n")
        line_number = (
            error.lineno - 1 - import_lines_count
        )  # Adjust for 0-based index and prepended imports
        error_offset = error.offset if error.offset is not None else -1

        if line_number < 0 or line_number >= len(lines):
            self.logging_utility.error(
                "Syntax error line number %s out of bounds for code block.",
                error.lineno,
            )
            return code, False

        problematic_line = lines[line_number]
        error_msg = error.msg.lower()

        # Fix 1: Indentation errors
        if "indentation" in error_msg or "indent" in error_msg:
            if "expected an indented block" in error_msg:
                if line_number > 0 and lines[line_number - 1].rstrip().endswith(":"):
                    lines[line_number] = "    " + problematic_line  # Add 4 spaces
                    return "\n".join(lines), True
            elif "unexpected indent" in error_msg:
                lines[line_number] = problematic_line.lstrip()  # Simple dedent
                return "\n".join(lines), True
            elif "unindent does not match any outer indentation level" in error_msg:
                for i in range(line_number - 1, -1, -1):
                    if lines[i].strip():
                        prev_indent = len(lines[i]) - len(lines[i].lstrip())
                        lines[line_number] = (
                            " " * prev_indent + problematic_line.lstrip()
                        )
                        return "\n".join(lines), True
                lines[line_number] = problematic_line.lstrip()  # Fallback dedent
                return "\n".join(lines), True

        # Fix 2: Missing parentheses in print
        elif "missing parentheses in call to 'print'" in error_msg:
            match = re.match(r"^\s*print\s+(.*)", problematic_line)
            if match:
                lines[line_number] = (
                    f"{match.group(0).split('print')[0]}print({match.group(1).rstrip()})"
                )
                return "\n".join(lines), True

        # Fix 3: Missing colon
        elif "expected ':'" in error_msg:
            if re.match(
                r"^\s*(if|for|while|def|class|try|except|finally|with)\b.*",
                problematic_line,
            ):  # Added word boundary \b
                if not problematic_line.rstrip().endswith(":"):
                    lines[line_number] = problematic_line.rstrip() + ":"
                    return "\n".join(lines), True

        # Fix 4: Unmatched quotes
        elif "eol while scanning string literal" in error_msg:
            single_quotes = problematic_line.count("'")
            double_quotes = problematic_line.count('"')
            # Check if inside triple quotes (basic check)
            if '"""' not in problematic_line and "'''" not in problematic_line:
                if single_quotes % 2 != 0:
                    lines[line_number] += "'"
                    return "\n".join(lines), True
                elif double_quotes % 2 != 0:
                    lines[line_number] += '"'
                    return "\n".join(lines), True

        return code, False

    async def execute_code_streaming(
        self, websocket: WebSocket, code: str, user_id: str = "test_user"
    ) -> None:

        tmp_script_path = None
        proc = None
        execution_id = f"{user_id}-{int(time.time() * 1000)}"
        self.current_execution_dir = self.base_generated_files_dir

        try:
            full_code = self.normalize_code(code)
            self.logging_utility.debug("Normalized Code:\n%s", full_code)

            try:
                ast.parse(full_code)
            except SyntaxError as e:
                error_lines = traceback.format_exception_only(type(e), e)
                error_message = "".join(error_lines).strip()
                await websocket.send_json(
                    {
                        "type": "error",
                        "error": f"Code contains syntax errors after normalization: {error_message}",
                        "line": e.lineno,
                        "offset": e.offset,
                        "text": e.text,
                    }
                )
                self.logging_utility.warning(
                    "AST validation failed for user %s after normalization: %s",
                    user_id,
                    error_message,
                )
                return

            if not self._validate_code_security(full_code):
                await websocket.send_json(
                    {"type": "error", "error": "Code violates security policy"}
                )
                self.logging_utility.warning(
                    "Security validation failed for user %s", user_id
                )
                return

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, dir=self.current_execution_dir
            ) as tmp:
                tmp.write(full_code)
                tmp_script_path = tmp.name

            self.last_executed_script_path = tmp_script_path
            script_sandbox_path = os.path.basename(tmp_script_path)

            self.logging_utility.info(
                "Executing script (host path): %s", tmp_script_path
            )
            self.logging_utility.info(
                "Executing script (sandbox path): %s", script_sandbox_path
            )

            disable_firejail = os.getenv("DISABLE_FIREJAIL", "false").lower() == "true"
            if os.name == "nt" or disable_firejail:
                cmd = ["python3", "-u", tmp_script_path]
                cwd = self.current_execution_dir
            else:
                firejail_base_cmd = ["firejail"] + self.security_profile[
                    "firejail_args"
                ]
                python_cmd = ["python3", "-u", script_sandbox_path]
                cmd = firejail_base_cmd + python_cmd
                cwd = None  # Let firejail handle CWD

            self.logging_utility.debug("Executing command: %s", " ".join(cmd))
            self.logging_utility.debug(
                "Execution CWD: %s", cwd if cwd else "Default (in sandbox)"
            )

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd,
            )
            self.active_processes[execution_id] = proc
            await self._stream_process_output(proc, websocket, execution_id)

            exit_code = await proc.wait()
            self.logging_utility.info(
                "Process %s finished with exit code: %s", execution_id, exit_code
            )
            if exit_code != 0:
                await websocket.send_json(
                    {
                        "type": "error",
                        "error": f"Code execution failed with exit code {exit_code}.",
                        "exit_code": exit_code,
                        "execution_id": execution_id,
                    }
                )

            uploaded_files = await self._upload_generated_files(
                user_id=user_id, execution_dir=self.current_execution_dir
            )
            await websocket.send_json(
                {
                    "type": "result",
                    "status": "complete",
                    "exit_code": exit_code,
                    "execution_id": execution_id,
                    "uploaded_files": uploaded_files,
                }
            )

        except WebSocketDisconnect:
            self.logging_utility.warning(
                "WebSocket disconnected during execution %s.", execution_id
            )
            if proc and proc.returncode is None:
                self.logging_utility.warning(
                    "Terminating process %s due to disconnect.", execution_id
                )
                try:
                    proc.terminate()
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    self.logging_utility.error(
                        "Process %s did not terminate gracefully, killing.",
                        execution_id,
                    )
                    proc.kill()
                except ProcessLookupError:
                    pass  # Already ended
                except Exception as term_err:
                    self.logging_utility.error(
                        "Error during process termination: %s", term_err
                    )
        except Exception as e:
            self.logging_utility.error(
                "Execution failed for %s: %s", execution_id, str(e), exc_info=True
            )
            try:
                await websocket.send_json(
                    {"type": "error", "error": f"An internal error occurred: {str(e)}"}
                )
            except Exception:
                pass
        finally:
            self.active_processes.pop(execution_id, None)
            if tmp_script_path and os.path.exists(tmp_script_path):
                try:
                    os.remove(tmp_script_path)
                    self.logging_utility.debug(
                        "Removed script file: %s", tmp_script_path
                    )
                except OSError as rm_err:
                    self.logging_utility.error(
                        "Error removing script file %s: %s", tmp_script_path, rm_err
                    )
            self.last_executed_script_path = None
            self.current_execution_dir = None
            try:
                if (
                    websocket.client_state != websocket.client_state.DISCONNECTED
                ):  # Check state before closing
                    await websocket.close()
                    self.logging_utility.debug(
                        "WebSocket closed for execution %s.", execution_id
                    )
            except RuntimeError as close_err:
                self.logging_utility.debug(
                    "WebSocket already closed or closing error for %s: %s",
                    execution_id,
                    close_err,
                )
            except Exception as final_close_err:
                self.logging_utility.error(
                    "Unexpected error closing WebSocket for %s: %s",
                    execution_id,
                    final_close_err,
                )

    # --- _stream_process_output (No changes) ---
    async def _stream_process_output(
        self, proc, websocket: WebSocket, execution_id: str
    ) -> None:
        buffer = ""
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(proc.stdout.read(1024), timeout=60.0)
                except asyncio.TimeoutError:
                    if execution_id not in self.active_processes:
                        break
                    if proc.returncode is not None:
                        break
                    self.logging_utility.error(
                        "Process %s might be hung, terminating.", execution_id
                    )
                    proc.terminate()
                    await websocket.send_json(
                        {"type": "error", "error": "Execution potentially hung."}
                    )
                    break

                if not chunk:
                    if buffer:
                        await websocket.send_json({"type": "stdout", "content": buffer})
                    break

                buffer += chunk.decode(errors="replace")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    await websocket.send_json(
                        {"type": "stdout", "content": line + "\n"}
                    )

            if buffer:
                await websocket.send_json({"type": "stdout", "content": buffer})

        except WebSocketDisconnect:
            self.logging_utility.warning(
                "WebSocket disconnected during streaming for %s.", execution_id
            )
            raise
        except ConnectionResetError:
            self.logging_utility.warning(
                "Connection reset during streaming for %s.", execution_id
            )
            raise WebSocketDisconnect
        except Exception as e:
            self.logging_utility.error(
                "Error during output streaming for %s: %s",
                execution_id,
                str(e),
                exc_info=True,
            )
            try:
                await websocket.send_json(
                    {"type": "error", "error": f"Error streaming output: {str(e)}"}
                )
            except Exception:
                pass

    # --- _validate_code_security (No changes) ---
    def _validate_code_security(self, code: str) -> bool:
        blocked_patterns = [
            r"(__import__|exec|eval|compile|input)\s*\(",
            r"(subprocess|os|sys)\.(system|popen|run|exec)",
            r"os\.(fork|kill|spawn)",
            r"multiprocessing\.(Process|Pool)",
            r"threading\.Thread",
            r"socket\.",
            r"import\s+(socket|subprocess|multiprocessing|ctypes|os|sys|shutil)",  # Consolidated imports
            r"ctypes\.",
            r"import\s+(ftplib|http\.client|requests|urllib|smtplib|telnetlib)",
            r"os\.(environ|putenv|unsetenv|chdir|fchdir|chroot|chmod|chown|lchown)",
            r"os\.(link|symlink|rename|replace|remove|unlink|rmdir|removedirs)",
            r"shutil\.(rmtree|move|copyfile|copy)",
            r"\.__class__",
            r"\.__subclasses__",
            r"\.__globals__",
            r"\.__builtins__",
        ]
        if any(re.search(p, code) for p in blocked_patterns):
            self.logging_utility.warning("Blocked pattern found matching code.")
            return False

        try:  # AST checks
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func_id = getattr(
                        node.func, "id", None
                    )  # Direct function calls like eval()
                    func_attr = getattr(
                        node.func, "attr", None
                    )  # Method calls like os.system()
                    func_mod = getattr(
                        getattr(node.func, "value", None), "id", None
                    )  # Module name like 'os'

                    if func_id in [
                        "exec",
                        "eval",
                        "compile",
                        "input",
                        "__import__",
                        "open",
                    ]:
                        self.logging_utility.warning(
                            "Blocked built-in call via AST: %s", func_id
                        )
                        return False
                    if func_mod in [
                        "os",
                        "sys",
                        "subprocess",
                        "shutil",
                    ] and func_attr in [
                        "system",
                        "popen",
                        "run",
                        "exec",
                        "fork",
                        "kill",
                        "spawn",
                        "remove",
                        "unlink",
                        "rmdir",
                        "removedirs",
                        "rmtree",
                        "move",
                        "chown",
                        "chmod",
                        "chroot",
                        "chdir",
                    ]:
                        self.logging_utility.warning(
                            "Blocked module call via AST: %s.%s", func_mod, func_attr
                        )
                        return False
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    module_names = []
                    if isinstance(node, ast.Import):
                        module_names = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        module_names = [node.module]

                    blocked_imports = {
                        "os",
                        "sys",
                        "subprocess",
                        "socket",
                        "ctypes",
                        "shutil",
                        "multiprocessing",
                        "ftplib",
                        "http",
                        "requests",
                        "urllib",
                        "smtplib",
                        "telnetlib",
                    }
                    if any(name in blocked_imports for name in module_names):
                        self.logging_utility.warning(
                            "Blocked import via AST: %s", module_names
                        )
                        return False
        except SyntaxError:
            return False  # Invalid syntax is not executable anyway
        except Exception as e:
            self.logging_utility.error("AST security validation error: %s", e)
            return False  # Fail safe

        return True

    async def _upload_generated_files(
        self, user_id: str, execution_dir: str
    ) -> List[dict]:  # Added type hint
        uploaded_files = []
        # Use ADMIN_API_KEY for the Entity client to authorize uploads
        admin_api_key = os.getenv("ADMIN_API_KEY")
        # Ensure BASE_URL points to the correct service (fastapi_cosmic_catalyst)
        base_url = os.getenv("ENTITIES_BASE_URL", "http://fastapi_cosmic_catalyst:9000")

        if not admin_api_key:
            self.logging_utility.error(
                "ADMIN_API_KEY environment variable not set. Cannot upload files."
            )
            return []  # Cannot proceed without auth

        # Instantiate the client here for clarity, using the admin key
        client = Entity(api_key=admin_api_key, base_url=base_url)

        async def upload_single_file(filename, file_path):
            # Skip directories and the script itself
            if os.path.isdir(file_path) or (
                self.last_executed_script_path
                and os.path.samefile(file_path, self.last_executed_script_path)
            ):
                return None

            try:
                self.logging_utility.info(
                    "Attempting upload via SDK for file: %s", file_path
                )

                upload_response = await asyncio.to_thread(
                    client.files.upload_file,
                    file_path=file_path,
                    purpose="assistants",

                )

                if not upload_response:  # Check if upload failed in the client
                    self.logging_utility.error(
                        "SDK upload_file returned None for %s", filename
                    )
                    return None

                self.logging_utility.info(
                    "File '%s' uploaded via SDK, got ID: %s. Getting signed URL.",
                    filename,
                    upload_response.id,
                )

                # *** CORRECTED SDK CALL ***
                # Remove label and markdown, pass use_real_filename directly

                signed_url = await asyncio.to_thread(
                    client.files.get_signed_url,
                    file_id=upload_response.id,
                    # expires_in=... # Optional: add if needed, e.g., expires_in=3600
                    use_real_filename=True,  # Pass correctly
                )

                if not signed_url:
                    self.logging_utility.error(
                        "Failed to get signed URL for file ID %s", upload_response.id
                    )
                    # Decide if you still want to return the file info without a URL
                    return {
                        "filename": filename,
                        "id": upload_response.id,
                        "url": None,
                    }  # Example: return with None URL

                self.logging_utility.info(
                    "Successfully uploaded '%s' (ID: %s) and got signed URL.",
                    filename,
                    upload_response.id,
                )
                return {
                    "filename": filename,
                    "id": upload_response.id,
                    "url": signed_url,
                }

            except FileNotFoundError:
                self.logging_utility.warning(
                    "File not found during upload attempt: %s", file_path
                )
                return None
            except Exception as e:
                # Log the specific exception from the SDK call
                self.logging_utility.error(
                    "Upload/SignedURL SDK call failed for '%s': %s",
                    filename,
                    str(e),
                    exc_info=True,
                )
                return None

        tasks = []
        if os.path.exists(execution_dir):
            for fname in os.listdir(execution_dir):
                fpath = os.path.join(execution_dir, fname)
                # Skip the matplotlib cache directory
                if os.path.abspath(fpath) == os.path.abspath(
                    self.mpl_cache_dir_host_path
                ):
                    continue
                # Check if it's a file
                if os.path.isfile(fpath):
                    # Skip the script file itself
                    if not (
                        self.last_executed_script_path
                        and os.path.samefile(fpath, self.last_executed_script_path)
                    ):
                        tasks.append(upload_single_file(fname, fpath))

        if tasks:
            results = await asyncio.gather(*tasks)
            uploaded_files = [
                res for res in results if res is not None
            ]  # Filter out None results from failures

        # --- Cleanup ---
        self.logging_utility.debug(
            "Starting cleanup of generated files in: %s", execution_dir
        )
        if os.path.exists(execution_dir):
            for fname in os.listdir(execution_dir):
                fpath = os.path.join(execution_dir, fname)
                # Skip persistent matplotlib cache dir
                if os.path.abspath(fpath) == os.path.abspath(
                    self.mpl_cache_dir_host_path
                ):
                    self.logging_utility.debug(
                        "Skipping cleanup of matplotlib cache: %s", fpath
                    )
                    continue
                try:
                    if os.path.isfile(fpath) or os.path.islink(fpath):
                        os.remove(fpath)
                        self.logging_utility.debug("Removed file/link: %s", fpath)
                    elif os.path.isdir(fpath):

                        pass
                except Exception as e:
                    self.logging_utility.error(
                        "Cleanup failed for %s: %s", fname, str(e)
                    )

        self.logging_utility.info(
            "File upload process finished. Uploaded files: %d", len(uploaded_files)
        )
        return uploaded_files
