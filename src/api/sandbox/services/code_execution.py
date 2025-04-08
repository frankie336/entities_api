import ast
import asyncio
import os
import re
import tempfile
import time
import traceback
from typing import Tuple

from dotenv import load_dotenv
from fastapi import WebSocket
from projectdavid import Entity
from sandbox.services.logging_service import LoggingUtility
from starlette.websockets import WebSocketDisconnect

load_dotenv()


class StreamingCodeExecutionHandler:
    def __init__(self):
        self.logging_utility = LoggingUtility()
        self.active_processes = {}
        self.generated_files_dir = os.path.abspath("generated_files")
        os.makedirs(self.generated_files_dir, exist_ok=True)
        self.last_executed_script_path = None

        self.logging_utility.info("Current working directory: %s", os.getcwd())
        self.logging_utility.info(
            "Generated files directory: %s", self.generated_files_dir
        )

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
            "import asyncio\n"
            "import math\n"
            "import time\n"
            "from datetime import datetime\n"
        )

    def normalize_code(self, code: str) -> str:
        # Fix curly quotes and other special characters
        replacements = {
            '"': '"',
            '"': '"',
            """: "'", """: "'",
            "\u00b2": "**2",
            "^": "**",
            "⇒": "->",
            "×": "*",
            "÷": "/",
        }
        for k, v in replacements.items():
            code = code.replace(k, v)
        code = re.sub(r"[^\x00-\x7F]+", "", code)

        # Handle line continuations and join continued lines
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

        # Fix up indentation
        formatted_lines = []
        indent_level = 0
        block_started = False

        # First pass: identify colon lines and calculate proper indentation
        for i, line in enumerate(lines):
            stripped = line.lstrip()

            # Skip empty lines
            if not stripped:
                formatted_lines.append("")
                continue

            # Calculate current indentation
            current_indent = len(line) - len(stripped)

            # Recalibrate indent_level based on the current line's indentation
            if i > 0 and block_started and current_indent > 0:
                # We've entered a block, use this indentation as the new block level
                block_started = False
                indent_size = current_indent

            # Determine expected indentation
            expected_indent = indent_level * indent_size

            # Apply correct indentation
            if stripped.endswith(":"):
                # This line starts a new block
                formatted_line = " " * expected_indent + stripped
                indent_level += 1
                block_started = True
            elif stripped.startswith(("return", "pass", "raise", "break", "continue")):
                # These keywords might indicate the end of a block
                if indent_level > 0:
                    indent_level -= 1
                expected_indent = indent_level * indent_size
                formatted_line = " " * expected_indent + stripped
            else:
                # Regular line, use expected indentation
                formatted_line = " " * expected_indent + stripped

            formatted_lines.append(formatted_line)

        # Second pass: ensure blocks have proper indentation
        final_lines = []
        i = 0
        while i < len(formatted_lines):
            line = formatted_lines[i]
            stripped = line.lstrip()

            if stripped.endswith(":"):
                # Check if the next line exists and is properly indented
                if i + 1 < len(formatted_lines) and not formatted_lines[i + 1].strip():
                    # Skip empty lines
                    final_lines.append(line)
                    final_lines.append("")
                    i += 2
                    continue

                if i + 1 < len(formatted_lines):
                    next_line = formatted_lines[i + 1]
                    next_stripped = next_line.lstrip()
                    current_indent = len(line) - len(stripped)
                    next_indent = len(next_line) - len(next_stripped)

                    if next_indent <= current_indent and next_stripped:
                        # The next line should be indented but isn't
                        # Insert a properly indented pass statement
                        indent_for_block = current_indent + indent_size
                        final_lines.append(line)
                        final_lines.append(" " * indent_for_block + "pass")
                    else:
                        final_lines.append(line)
                else:
                    # This is the last line and ends with a colon
                    final_lines.append(line)
                    final_lines.append(
                        " " * (len(line) - len(stripped) + indent_size) + "pass"
                    )
            else:
                final_lines.append(line)
            i += 1

        normalized_code = "\n".join(final_lines)

        # Handle single expression that might need to be wrapped in print()
        if re.match(r"^[\w\.]+\s*\(.*\)\s*$", normalized_code.strip()):
            normalized_code = f"print({normalized_code.strip()})"

        # AST validation and error correction
        normalized_code = self._ast_validate_and_fix(normalized_code)

        return self.required_imports + normalized_code

    def _ast_validate_and_fix(self, code: str) -> str:
        """
        Validate code using AST parsing and attempt to fix common syntax errors.
        Returns the fixed code or the original if validation passes.
        """
        try:
            # Try to parse the code with AST
            ast.parse(code)
            # If successful, no changes needed
            return code
        except SyntaxError as e:
            self.logging_utility.warning(
                "AST validation failed: %s at line %s", e.msg, e.lineno
            )
            # Attempt to fix common syntax errors
            fixed_code, success = self._fix_common_syntax_errors(code, e)
            if success:
                self.logging_utility.info("Successfully fixed syntax errors")
                return fixed_code
            # If we couldn't fix it, return the original and let the execution fail with better error messages
            return code

    def _fix_common_syntax_errors(
        self, code: str, error: SyntaxError
    ) -> Tuple[str, bool]:
        """
        Attempts to fix common syntax errors based on the error message and location.
        Returns a tuple containing (fixed_code, success_flag).
        """
        lines = code.split("\n")
        line_number = error.lineno - 1  # Adjust for 0-based indexing

        # Handle out of bounds
        if line_number >= len(lines) or line_number < 0:
            return code, False

        # Get the problematic line and the error message
        problematic_line = lines[line_number]
        error_msg = error.msg.lower()

        # Fix 1: Indentation errors
        if "indentation" in error_msg:
            # Check if this is an 'expected an indented block' error
            if "expected an indented block" in error_msg:
                # Find the previous line that should have started a block
                prev_line = lines[line_number - 1] if line_number > 0 else ""
                if prev_line.rstrip().endswith(":"):
                    # Calculate proper indentation
                    current_indent = len(problematic_line) - len(
                        problematic_line.lstrip()
                    )
                    # Add 4 spaces of indentation
                    lines[line_number] = (
                        " " * (current_indent + 4) + problematic_line.lstrip()
                    )
                    return "\n".join(lines), True

            # Check if this is an 'unexpected indent' error
            elif "unexpected indent" in error_msg:
                # Reduce indentation to match previous line
                prev_line = lines[line_number - 1] if line_number > 0 else ""
                prev_indent = len(prev_line) - len(prev_line.lstrip())
                lines[line_number] = " " * prev_indent + problematic_line.lstrip()
                return "\n".join(lines), True

        # Fix 2: Missing parentheses
        elif "parentheses" in error_msg:
            if "(" in problematic_line and ")" not in problematic_line:
                lines[line_number] = problematic_line + ")"
                return "\n".join(lines), True

        # Fix 3: Missing colon after if/for/while/def/class
        elif "expected" in error_msg and ":" in error_msg:
            if any(
                keyword in problematic_line
                for keyword in ["if", "for", "while", "def", "class"]
            ):
                if not problematic_line.rstrip().endswith(":"):
                    lines[line_number] = problematic_line.rstrip() + ":"
                    return "\n".join(lines), True

        # Fix 4: Unmatched quotes
        elif "eol while scanning" in error_msg and "string literal" in error_msg:
            if ("'" in problematic_line and problematic_line.count("'") % 2 != 0) or (
                '"' in problematic_line and problematic_line.count('"') % 2 != 0
            ):
                # Find the type of quote used
                quote_type = "'" if "'" in problematic_line else '"'
                lines[line_number] = problematic_line + quote_type
                return "\n".join(lines), True

        # Fix 5: Missing commas in collection literals
        elif "invalid syntax" in error_msg:
            # Check for list/dict/tuple literals with missing commas
            if (
                ("[" in problematic_line and "]" in problematic_line)
                or ("{" in problematic_line and "}" in problematic_line)
                or ("(" in problematic_line and ")" in problematic_line)
            ):
                # This is a heuristic and might not always be correct
                # Replace spaces between items with commas (simple cases only)
                fixed_line = re.sub(r"(\w+)\s+(\w+)", r"\1, \2", problematic_line)
                if fixed_line != problematic_line:
                    lines[line_number] = fixed_line
                    return "\n".join(lines), True

        # No fix identified or implemented
        return code, False

    async def execute_code_streaming(
        self, websocket: WebSocket, code: str, user_id: str = "test_user"
    ) -> None:

        tmp_path = None
        try:
            full_code = self.normalize_code(code)

            # Try to parse with AST for additional validation before execution
            try:
                ast.parse(full_code)
            except SyntaxError as e:
                error_lines = traceback.format_exception_only(type(e), e)
                error_message = "".join(error_lines)
                await websocket.send_json(
                    {
                        "error": f"Code contains syntax errors: {error_message}",
                        "line": e.lineno,
                        "offset": e.offset,
                        "text": e.text,
                    }
                )
                self.logging_utility.warning(
                    "AST validation failed for user %s: %s", user_id, error_message
                )
                return

            if not self._validate_code_security(full_code):
                await websocket.send_json({"error": "Code violates security policy"})
                self.logging_utility.warning(
                    "Security validation failed for user %s", user_id
                )
                return

            execution_id = f"{user_id}-{int(time.time() * 1000)}"

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, dir=self.generated_files_dir
            ) as tmp:
                tmp.write(full_code)
                tmp_path = tmp.name

            self.last_executed_script_path = tmp_path
            self.logging_utility.info("Normalized code written to: %s", tmp_path)

            disable_firejail = os.getenv("DISABLE_FIREJAIL", "false").lower() == "true"
            cmd = (
                ["python3", "-u", tmp_path]
                if os.name == "nt" or disable_firejail
                else [
                    "firejail",
                    *self.security_profile["firejail_args"],
                    "python3",
                    "-u",
                    tmp_path,
                ]
            )

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=(
                    None
                    if os.name != "nt" and not disable_firejail
                    else self.generated_files_dir
                ),
            )
            self.active_processes[execution_id] = proc
            await self._stream_process_output(proc, websocket, execution_id)

            uploaded_files = await self._upload_generated_files(user_id=user_id)
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

    async def _stream_process_output(
        self, proc, websocket: WebSocket, execution_id: str
    ) -> None:
        try:
            while True:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=30)
                if not line:
                    break
                await websocket.send_text(line.decode(errors="replace"))

            return_code = await proc.wait()
            await websocket.send_json(
                {
                    "status": "process_complete",
                    "exit_code": return_code,
                    "execution_id": execution_id,
                }
            )
        except asyncio.TimeoutError:
            self.logging_utility.error(
                "Timeout occurred for execution_id: %s", execution_id
            )
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
        client = Entity(base_url="http://fastapi_cosmic_catalyst:9000")

        try:
            user = client.users.create_user(name="test_user")
        except Exception as e:
            self.logging_utility.error("Failed to create user: %s", str(e))
            return uploaded_files

        async def upload_single_file(filename, file_path):
            try:
                upload = client.files.upload_file(
                    file_path=file_path, user_id=user.id, purpose="assistants"
                )

                file_url = client.files.get_signed_url(
                    upload.id, label=filename, markdown=True, use_real_filename=True
                )

                return {"filename": filename, "id": upload.id, "url": file_url}
            except Exception as e:
                self.logging_utility.error("Upload failed for %s: %s", filename, str(e))
                return None

        tasks = [
            upload_single_file(fname, os.path.join(self.generated_files_dir, fname))
            for fname in os.listdir(self.generated_files_dir)
            if os.path.isfile(os.path.join(self.generated_files_dir, fname))
            and not self.last_executed_script_path
            or not os.path.samefile(
                os.path.join(self.generated_files_dir, fname),
                self.last_executed_script_path,
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
