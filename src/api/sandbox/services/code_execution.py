# src/api/entities_api/platform_tools/code_interpreter/code_execution_handler.py

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

        # Directory for any generated output & caches
        self.generated_files_dir = os.path.abspath("generated_files")
        os.makedirs(self.generated_files_dir, exist_ok=True)

        # ─── Redirect Matplotlib cache to a writable location ───
        self.mpl_config_dir = os.path.join(self.generated_files_dir, "mplcache")
        os.makedirs(self.mpl_config_dir, exist_ok=True)
        os.environ["MPLCONFIGDIR"] = self.mpl_config_dir
        self.logging_utility.info("MPLCONFIGDIR set to %s", self.mpl_config_dir)

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
                    # Ensure MPLCONFIGDIR is passed through firejail if used
                    f"--env=MPLCONFIGDIR={self.mpl_config_dir}",
                ]
            )
        }

        # These imports get prepended to all user code
        self.required_imports = (
            "import asyncio\n"
            "import math\n"
            "import time\n"
            "from datetime import datetime\n"
            # Add common data science imports
            "import pandas as pd\n"
            "import numpy as np\n"
            "import matplotlib.pyplot as plt\n"
            "import seaborn as sns\n"
            # Configure matplotlib backend for non-interactive use
            "import matplotlib\n"
            "matplotlib.use('Agg')\n"
        )

    def normalize_code(self, code: str) -> str:
        # Fix curly quotes and other special characters
        replacements = {
            '“': '"', '”': '"',  # Double quotes
            '‘': "'", '’': "'",  # Single quotes
            "\u00b2": "**2",     # Superscript 2
            "^": "**",           # Caret for exponentiation
            "⇒": "->",           # Right arrow
            "×": "*",           # Multiplication sign
            "÷": "/",           # Division sign
        }
        for k, v in replacements.items():
            code = code.replace(k, v)
        # Remove remaining non-ASCII characters that might cause issues
        code = re.sub(r'[^\x00-\x7F]+', '', code)

        # Handle line continuations and join continued lines carefully
        lines = []
        current_line = ""
        for line in code.split('\n'):
            stripped_line = line.rstrip()
            if stripped_line.endswith('\\'):
                current_line += stripped_line[:-1] + " " # Remove backslash and add space
            else:
                current_line += stripped_line
                lines.append(current_line)
                current_line = ""
        if current_line: # Add any remaining part
             lines.append(current_line)

        # Basic indentation fixing (more robust logic follows)
        formatted_lines = []
        current_indent = 0
        indent_size = 4 # Default indent size

        for i, line in enumerate(lines):
            stripped_line = line.lstrip()
            if not stripped_line: # Keep empty lines
                formatted_lines.append("")
                continue

            # Calculate actual indent of the current line
            line_indent = len(line) - len(stripped_line)

            # Check for dedentation keywords
            if stripped_line.startswith(("elif", "else", "except", "finally")):
                 # These keywords should align with the start of their block
                 # We'll rely on the AST check or later passes to fully correct this
                 pass # Simple pass for now, AST/later logic handles complex cases
            elif stripped_line.startswith(("return", "pass", "raise", "break", "continue")):
                 # These often signal end of block, but not always, be cautious
                 pass # Avoid aggressive dedenting here

            # Add the line with potentially adjusted indent (initial guess)
            # A more sophisticated pass might be needed, but AST validation helps
            formatted_lines.append(" " * current_indent + stripped_line)

            # Adjust indent for the *next* line if this line ends with a colon
            if stripped_line.endswith(":"):
                current_indent += indent_size
            # If the line caused a dedent (like return/break), adjust back *after* adding line
            # This part is tricky and prone to errors, AST validation is key
            # Minimal logic here to avoid breaking valid code
            # Example: if after an 'if:' the next line is less indented, it implies dedent
            if i + 1 < len(lines):
                 next_line_stripped = lines[i+1].lstrip()
                 if next_line_stripped:
                     next_line_indent = len(lines[i+1]) - len(next_line_stripped)
                     if next_line_indent < current_indent and not stripped_line.endswith(":"):
                          # Potential dedent detected by next line's indent
                          current_indent = next_line_indent

        normalized_code = "\n".join(formatted_lines)

        # Wrap potential single expressions in print() for output
        # Be careful not to wrap assignments or definitions
        stripped_normalized = normalized_code.strip()
        try:
            # Attempt to parse the code as is first
            parsed = ast.parse(stripped_normalized)
            if len(parsed.body) == 1 and isinstance(parsed.body[0], ast.Expr):
                 # It's a single expression, wrap it in print
                 # Avoid wrapping if it's already a print call
                 is_print_call = False
                 if isinstance(parsed.body[0].value, ast.Call):
                     if isinstance(parsed.body[0].value.func, ast.Name) and parsed.body[0].value.func.id == 'print':
                         is_print_call = True
                 if not is_print_call:
                     normalized_code = f"print({stripped_normalized})"
                     self.logging_utility.debug("Wrapped single expression in print()")

        except SyntaxError:
             # If parsing fails here, let the later AST check handle it
             self.logging_utility.warning("Initial parse for print-wrapping failed, proceeding.")
             pass

        # Final AST validation and potential error correction
        normalized_code = self._ast_validate_and_fix(normalized_code)

        return self.required_imports + "\n" + normalized_code

    def _ast_validate_and_fix(self, code: str) -> str:
        """
        Validate code using AST parsing and attempt to fix common syntax errors.
        Returns the fixed code or the original if validation passes/fix fails.
        """
        try:
            ast.parse(code)
            self.logging_utility.debug("AST validation passed.")
            return code
        except SyntaxError as e:
            self.logging_utility.warning(
                "AST validation failed: %s at line %s, offset %s. Text: %s",
                e.msg, e.lineno, e.offset, e.text.strip() if e.text else "N/A"
            )
            fixed_code, success = self._fix_common_syntax_errors(code, e)
            if success:
                self.logging_utility.info("Attempted automatic syntax fix.")
                # Re-validate after fixing
                try:
                    ast.parse(fixed_code)
                    self.logging_utility.info("Syntax fix successful and validated.")
                    return fixed_code
                except SyntaxError as e2:
                    self.logging_utility.warning("Syntax fix failed validation: %s", e2.msg)
                    # Revert to original code if fix introduced new errors
                    return code
            else:
                # If no fix was attempted or successful, return original code
                # The execution will likely fail, providing a clearer error from Python itself
                return code
        except Exception as ex:
             self.logging_utility.error(f"Unexpected error during AST validation: {ex}")
             return code # Return original code on unexpected errors


    def _fix_common_syntax_errors(
        self, code: str, error: SyntaxError
    ) -> Tuple[str, bool]:
        """
        Attempts to fix common syntax errors based on the error message and location.
        Returns a tuple containing (fixed_code, success_flag). More robust fixing.
        """
        lines = code.split('\n')
        # Adjust line number for 0-based index, considering potential prepended imports later
        line_number = error.lineno - 1 - self.required_imports.count('\n') -1 # Adjust for required imports
        if line_number < 0: line_number = 0 # Clamp if adjustment goes too low
        if line_number >= len(lines): return code, False # Safety check

        problematic_line = lines[line_number]
        error_msg = error.msg.lower()
        offset = error.offset if error.offset is not None else len(problematic_line)

        self.logging_utility.debug(f"Attempting fix for '{error_msg}' on line {line_number+1}: '{problematic_line}'")

        # Fix 1: Indentation errors
        if "indentation error" in error_msg or "indent" in error_msg:
            if "expected an indented block" in error_msg:
                # Likely missing indent after a colon ':'
                if line_number > 0 and lines[line_number-1].rstrip().endswith(':'):
                    prev_indent = len(lines[line_number-1]) - len(lines[line_number-1].lstrip())
                    lines[line_number] = " " * (prev_indent + 4) + problematic_line.lstrip()
                    return "\n".join(lines), True
                # Sometimes it might expect indent without a preceding colon (rare, maybe inside multiline structures)
                # Add a simple 'pass' statement with indent if line is empty or seems misplaced
                if not problematic_line.strip():
                     prev_indent = 0
                     if line_number > 0:
                         prev_indent = len(lines[line_number-1]) - len(lines[line_number-1].lstrip())
                     lines[line_number] = " " * (prev_indent + 4) + "pass"
                     return "\n".join(lines), True


            elif "unindent does not match any outer indentation level" in error_msg:
                # Find the closest valid outer indentation level
                target_indent = 0
                for i in range(line_number - 1, -1, -1):
                    line_indent = len(lines[i]) - len(lines[i].lstrip())
                    if line_indent < (len(problematic_line) - len(problematic_line.lstrip())):
                         # Check if the structure allows this dedent (e.g., not right after ':')
                         if not lines[i].rstrip().endswith(':'):
                            target_indent = line_indent
                            break
                lines[line_number] = " " * target_indent + problematic_line.lstrip()
                return "\n".join(lines), True

            elif "unexpected indent" in error_msg:
                 # Reduce indent, potentially aligning with previous non-empty line's base indent
                 target_indent = 0
                 for i in range(line_number - 1, -1, -1):
                     if lines[i].strip(): # Find previous non-empty line
                          target_indent = len(lines[i]) - len(lines[i].lstrip())
                          # If prev line ended with ':', this indent might be correct, don't change
                          if lines[i].rstrip().endswith(':'):
                              target_indent += 4 # Assume expected indent
                              break # Stop searching
                          else:
                              break # Found suitable indent level
                 lines[line_number] = " " * target_indent + problematic_line.lstrip()
                 return "\n".join(lines), True


        # Fix 2: Missing parentheses in print (Python 3) or function calls
        elif "missing parentheses in call to" in error_msg or ("invalid syntax" in error_msg and error.text and error.text.strip() == 'print'):
             match = re.match(r"^\s*print\s+('.*'|\".*\"|[\w\.]+.*)", problematic_line)
             if match:
                 content = match.group(1).strip()
                 lines[line_number] = problematic_line.split('print')[0] + f"print({content})"
                 return "\n".join(lines), True
        elif "unexpected EOF while parsing" in error_msg and offset > len(problematic_line):
             # Often due to unclosed parenthesis/bracket/brace on the *last* line
             open_brackets = problematic_line.count('(') - problematic_line.count(')')
             open_squares = problematic_line.count('[') - problematic_line.count(']')
             open_curlies = problematic_line.count('{') - problematic_line.count('}')
             fixed_line = problematic_line
             if open_brackets > 0: fixed_line += ")" * open_brackets
             if open_squares > 0: fixed_line += "]" * open_squares
             if open_curlies > 0: fixed_line += "}" * open_curlies
             if fixed_line != problematic_line:
                 lines[line_number] = fixed_line
                 return "\n".join(lines), True


        # Fix 3: Missing colon after if/for/while/def/class
        elif "invalid syntax" in error_msg and offset >= len(problematic_line.rstrip()):
             stripped = problematic_line.rstrip()
             if any(stripped.startswith(k + " ") or stripped == k for k in ["if", "for", "while", "def", "class", "try", "except", "finally", "with", "elif", "else"]) and not stripped.endswith(":"):
                 lines[line_number] = stripped + ":"
                 return "\n".join(lines), True


        # Fix 4: Unmatched quotes
        elif "eol while scanning string literal" in error_msg:
            line = problematic_line
            # Count occurrences of single and double quotes
            single_quotes = line.count("'")
            double_quotes = line.count('"')
            # Check if the error offset suggests the end of the line
            if offset >= len(line):
                # Check for triple quotes first
                if line.count("'''") % 2 != 0:
                    lines[line_number] = line + "'''"
                    return "\n".join(lines), True
                if line.count('"""') % 2 != 0:
                     lines[line_number] = line + '"""'
                     return "\n".join(lines), True
                # Then check single/double quotes
                if double_quotes > 0 and double_quotes % 2 != 0:
                    lines[line_number] = line + '"'
                    return "\n".join(lines), True
                if single_quotes > 0 and single_quotes % 2 != 0:
                    lines[line_number] = line + "'"
                    return "\n".join(lines), True


        # Fix 5: Missing commas in collection literals (simple heuristic)
        elif "invalid syntax" in error_msg and offset > 0:
            # Look for patterns like 'item1 item2' inside brackets/braces
            # This is risky and might break valid code (e.g., string formatting)
            # Try only if offset points *between* two likely items
            char_before = problematic_line[offset-1] if offset > 0 else ''
            char_after = problematic_line[offset] if offset < len(problematic_line) else ''

            if char_before.isspace() and (char_after.isalnum() or char_after in ['"', "'", '(', '[']):
                # Check context: Are we inside brackets/braces?
                in_list = problematic_line[:offset].rfind('[') > problematic_line[:offset].rfind(']')
                in_tuple = problematic_line[:offset].rfind('(') > problematic_line[:offset].rfind(')') # Careful with calls
                in_dict_key = problematic_line[:offset].rfind('{') > problematic_line[:offset].rfind('}')
                # This needs refinement - checking for ':' for dicts etc.
                # Simplified: if looks like two items next to each other inside [], {}, ()
                if in_list or in_dict_key or in_tuple: # Add checks to avoid fixing function calls
                     if not re.search(r"\w+\s*\(", problematic_line[:offset]): # Avoid fixing inside function calls
                         lines[line_number] = problematic_line[:offset] + ',' + problematic_line[offset:]
                         return "\n".join(lines), True


        # No fix identified or applied
        self.logging_utility.debug("No specific fix applied for this syntax error.")
        return code, False


    async def execute_code_streaming(
        self, websocket: WebSocket, code: str, user_id: str = "test_user"
    ) -> None:

        tmp_path = None
        execution_id = f"{user_id}-{int(time.time() * 1000)}" # Generate ID early for logging

        try:
            self.logging_utility.info(f"[{execution_id}] Received code execution request from user {user_id}.")
            self.logging_utility.debug(f"[{execution_id}] Original code:\n---\n{code}\n---")

            full_code = self.normalize_code(code)
            self.logging_utility.info(f"[{execution_id}] Normalization and AST fixing complete.")
            self.logging_utility.debug(f"[{execution_id}] Normalized code:\n---\n{full_code}\n---")

            # Final security validation on the processed code
            if not self._validate_code_security(full_code):
                error_msg = "Code violates security policy (blocked imports or functions detected)."
                await websocket.send_json({"error": error_msg, "execution_id": execution_id})
                self.logging_utility.warning(f"[{execution_id}] Security validation failed for user {user_id}.")
                return

            self.logging_utility.info(f"[{execution_id}] Security validation passed.")

            # Write the final code to a temporary file
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, dir=self.generated_files_dir, encoding='utf-8'
            ) as tmp:
                tmp.write(full_code)
                tmp_path = tmp.name

            self.last_executed_script_path = tmp_path
            self.logging_utility.info(f"[{execution_id}] Normalized code written to: {tmp_path}")

            disable_firejail = os.getenv("DISABLE_FIREJAIL", "false").lower() == "true"
            cmd = []
            if os.name == "nt" or disable_firejail:
                cmd = ["python3", "-u", tmp_path]
                cwd = self.generated_files_dir # Run directly in generated_files dir if no firejail
                self.logging_utility.info(f"[{execution_id}] Executing without Firejail.")
            else:
                cmd = ["firejail", *self.security_profile["firejail_args"], "python3", "-u", tmp_path]
                # Firejail with --private handles the working directory implicitly
                cwd = None # Let firejail manage the private directory as CWD
                self.logging_utility.info(f"[{execution_id}] Executing with Firejail.")

            self.logging_utility.debug(f"[{execution_id}] Execution command: {' '.join(cmd)}")

            # Prepare environment for the subprocess
            proc_env = os.environ.copy()
            proc_env["MPLCONFIGDIR"] = self.mpl_config_dir # Ensure matplotlib cache dir is set

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT, # Redirect stderr to stdout
                cwd=cwd,
                env=proc_env,
            )
            self.active_processes[execution_id] = proc
            self.logging_utility.info(f"[{execution_id}] Subprocess created (PID: {proc.pid}). Streaming output.")

            await self._stream_process_output(proc, websocket, execution_id)

            # Check process exit code after streaming finishes
            exit_code = proc.returncode
            self.logging_utility.info(f"[{execution_id}] Process finished with exit code: {exit_code}.")

            if exit_code == 0:
                 # Upload files only on successful execution
                 self.logging_utility.info(f"[{execution_id}] Uploading generated files.")
                 uploaded_files = await self._upload_generated_files(user_id=user_id, execution_id=execution_id)
                 await websocket.send_json(
                     {
                         "status": "complete",
                         "execution_id": execution_id,
                         "uploaded_files": uploaded_files,
                         "exit_code": exit_code,
                     }
                 )
                 self.logging_utility.info(f"[{execution_id}] Execution complete. Sent completion status.")
            else:
                 # Send error status if process exited non-zero, output was already streamed
                 error_msg = f"Code execution failed with exit code {exit_code}."
                 await websocket.send_json({
                     "status": "error",
                     "error": error_msg,
                     "execution_id": execution_id,
                     "exit_code": exit_code,
                 })
                 self.logging_utility.error(f"[{execution_id}] Execution failed. Sent error status.")


        except WebSocketDisconnect:
             self.logging_utility.warning(f"[{execution_id}] WebSocket disconnected by client.")
             # Terminate the process if it's still running
             if execution_id in self.active_processes:
                 proc = self.active_processes.pop(execution_id)
                 try:
                     proc.terminate()
                     await proc.wait() # Ensure termination
                     self.logging_utility.info(f"[{execution_id}] Terminated process due to client disconnect.")
                 except ProcessLookupError:
                     self.logging_utility.debug(f"[{execution_id}] Process already terminated.")
                 except Exception as term_ex:
                     self.logging_utility.error(f"[{execution_id}] Error terminating process: {term_ex}")

        except Exception as e:
            error_msg = f"An unexpected error occurred during execution: {str(e)}"
            self.logging_utility.error(f"[{execution_id}] Execution failed: {error_msg}", exc_info=True)
            detailed_tb = traceback.format_exc()
            self.logging_utility.debug(f"[{execution_id}] Traceback:\n{detailed_tb}")
            try:
                # Send error details over websocket if possible
                await websocket.send_json({"error": error_msg, "details": detailed_tb, "execution_id": execution_id})
            except Exception as ws_err:
                 self.logging_utility.error(f"[{execution_id}] Failed to send error details over WebSocket: {ws_err}")
        finally:
            # Clean up the temporary script file
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                    self.logging_utility.info(f"[{execution_id}] Removed temporary script file: {tmp_path}")
                except OSError as rm_err:
                    self.logging_utility.error(f"[{execution_id}] Failed to remove temporary script {tmp_path}: {rm_err}")
            self.last_executed_script_path = None

            # Remove process from active list if it's still there
            if execution_id in self.active_processes:
                 self.active_processes.pop(execution_id, None)
                 self.logging_utility.debug(f"[{execution_id}] Removed process from active list.")

            # Attempt to close the websocket gracefully
            try:
                await websocket.close()
                self.logging_utility.debug(f"[{execution_id}] WebSocket closed.")
            except RuntimeError as close_err:
                 # Ignore error if websocket is already closed (e.g., due to disconnect)
                 if "WebSocket is not connected" in str(close_err):
                      self.logging_utility.debug(f"[{execution_id}] WebSocket already closed.")
                 else:
                      self.logging_utility.error(f"[{execution_id}] Error closing WebSocket: {close_err}")
            except Exception as final_close_err:
                 self.logging_utility.error(f"[{execution_id}] Unexpected error during WebSocket close: {final_close_err}")


    async def _stream_process_output(
        self, proc: asyncio.subprocess.Process, websocket: WebSocket, execution_id: str
    ) -> None:
        """Streams stdout/stderr from the process to the WebSocket."""
        output_buffer = ""
        MAX_BUFFER_SIZE = 1024 * 10 # 10 KB buffer before forced send

        try:
            while True:
                try:
                    # Read with a timeout to prevent blocking indefinitely
                    line_bytes = await asyncio.wait_for(proc.stdout.readline(), timeout=60.0)
                    if not line_bytes:
                        # End of stream
                        if output_buffer: # Send any remaining buffered output
                            await websocket.send_text(output_buffer)
                            output_buffer = ""
                        break

                    line = line_bytes.decode(errors="replace").replace('\r\n', '\n').replace('\r', '\n')
                    output_buffer += line

                    # Send output when buffer fills, a newline occurs, or periodically
                    if '\n' in output_buffer or len(output_buffer) > MAX_BUFFER_SIZE:
                        await websocket.send_text(output_buffer)
                        output_buffer = "" # Reset buffer

                except asyncio.TimeoutError:
                     self.logging_utility.warning(f"[{execution_id}] Timeout waiting for process output. Process still running? (PID: {proc.pid})")
                     # Check if process is still alive, terminate if needed? Or just continue waiting?
                     # For now, we just continue waiting, but log the timeout.
                     # If buffer has content, send it to show progress
                     if output_buffer:
                         await websocket.send_text(output_buffer)
                         output_buffer = ""
                     # Check if process ended unexpectedly during timeout wait
                     if proc.returncode is not None:
                         self.logging_utility.info(f"[{execution_id}] Process ended during output wait timeout.")
                         break
                     continue # Continue the loop waiting for more output

            # One final check for process completion status after loop exit
            await proc.wait() # Ensure process has fully exited
            self.logging_utility.debug(f"[{execution_id}] Output streaming finished.")

        except WebSocketDisconnect:
             self.logging_utility.warning(f"[{execution_id}] Client disconnected during output streaming.")
             # Process termination is handled in the calling function's except block
             raise # Re-raise to be caught by the main handler

        except ConnectionResetError:
             self.logging_utility.warning(f"[{execution_id}] Connection reset during output streaming.")
             raise WebSocketDisconnect # Treat as disconnect

        except Exception as e:
            error_msg = f"Error during output streaming: {str(e)}"
            self.logging_utility.error(f"[{execution_id}] {error_msg}", exc_info=True)
            try:
                await websocket.send_json({"error": error_msg, "execution_id": execution_id})
            except Exception as ws_err:
                 self.logging_utility.error(f"[{execution_id}] Failed to send streaming error over WebSocket: {ws_err}")
        finally:
             # Ensure any final buffered output is sent if websocket still connected
             if output_buffer:
                  try:
                      await websocket.send_text(output_buffer)
                  except Exception:
                      pass # Ignore if websocket closed


    def _validate_code_security(self, code: str) -> bool:
        """Performs security checks on the code string."""
        # More comprehensive list of potentially dangerous patterns
        blocked_patterns = [
            # Filesystem access (restrict to relative paths if needed, but generally block direct os calls)
            r"os\.(remove|unlink|rmdir|removedirs|rename|renames|chmod|chown|link|symlink)",
            r"os\.path\.abspath", # Prevent finding absolute paths easily
            r"open\s*\(\s*['\"]/", # Prevent opening absolute paths '/'
            r"open\s*\(\s*['\"].*\.\.", # Prevent '..' path traversal

            # Subprocess execution
            r"(__import__|exec|eval|compile)\s*\(", # Basic dangerous builtins
            r"(subprocess|os|sys)\.(system|popen|spawn|call|run|check_call|check_output)",
            r"pty\.(spawn)",
            r"commands\.(getoutput|getstatusoutput)", # Legacy module

            # Network access (allow specific libraries like requests if needed, but block low-level)
            r"socket\.", # Block direct socket usage
            # r"urllib\.", # Might be too restrictive, allow specific submodules if necessary
            # r"requests\.", # Allow if needed for API calls

            # System interaction / Information gathering
            r"sys\.(executable|platform|path|modules|argv)",
            r"os\.(get(?:pid|ppid|login|uid|gid|euid|egid)|uname|environ|getenv|putenv)", # Block sensitive info/env manipulation
            r"platform\.", # Block platform module
            r"ctypes\.", # Block C interface
            r"multiprocessing\.", # Block creating new processes easily

            # Imports of dangerous modules (redundant with function calls but good defense-in-depth)
            r"import\s+(os|sys|subprocess|pty|platform|ctypes|multiprocessing|shutil)",
            r"from\s+(os|sys|subprocess|pty|platform|ctypes|multiprocessing|shutil)\s+import",

            # Dangerous decorators or metaclasses (advanced)
            # (This is harder to detect reliably with regex)
        ]

        # Allow specific exceptions if necessary, e.g., allow os.path.join but not os.remove
        allowed_exceptions = [
             r"os\.path\.join", # Usually safe
             r"os\.path\.exists", # Usually safe
             r"os\.makedirs", # Needed for matplotlib cache, check if it uses self.generated_files_dir?
             # Be cautious adding exceptions
        ]

        # Remove allowed exceptions from the code before checking blocked patterns
        temp_code = code
        for allowed in allowed_exceptions:
             temp_code = re.sub(allowed, "__ALLOWED_FUNC__", temp_code)

        # Check for blocked patterns
        for pattern in blocked_patterns:
            if re.search(pattern, temp_code):
                self.logging_utility.warning(f"Blocked pattern detected: {pattern}")
                return False

        # Check AST for more subtle issues (e.g., attribute access on imported modules)
        try:
             tree = ast.parse(code)
             for node in ast.walk(tree):
                 # Example: Check for accessing sensitive attributes like os.environ
                 if isinstance(node, ast.Attribute):
                     # Get the full attribute chain (e.g., os.environ.get)
                     attr_chain = []
                     curr = node
                     while isinstance(curr, ast.Attribute):
                         attr_chain.insert(0, curr.attr)
                         curr = curr.value
                     if isinstance(curr, ast.Name):
                         attr_chain.insert(0, curr.id)

                     full_attr = ".".join(attr_chain)
                     # Define sensitive attributes/methods here
                     sensitive_attrs = {
                         "os.environ", "os.system", "os.remove", "sys.exit",
                         # Add more based on security policy
                     }
                     if full_attr in sensitive_attrs:
                          self.logging_utility.warning(f"Blocked sensitive attribute access via AST: {full_attr}")
                          return False
                 # Example: Check for imports again via AST
                 elif isinstance(node, (ast.Import, ast.ImportFrom)):
                      blocked_modules = {"os", "sys", "subprocess", "ctypes", "shutil", "pty"}
                      if isinstance(node, ast.Import):
                          for alias in node.names:
                              if alias.name in blocked_modules:
                                   self.logging_utility.warning(f"Blocked import via AST: {alias.name}")
                                   return False
                      elif isinstance(node, ast.ImportFrom):
                           if node.module in blocked_modules:
                                self.logging_utility.warning(f"Blocked from import via AST: {node.module}")
                                return False
        except Exception as ast_ex:
             self.logging_utility.error(f"AST security check failed: {ast_ex}")
             # Fail safe: if AST parsing fails during security check, deny execution
             return False


        return True


    async def _upload_generated_files(self, user_id: str, execution_id: str) -> list:
        """Uploads files generated during execution and returns their details."""
        uploaded_files = []
        # Ensure client uses the correct base URL from env or config
        base_url = os.getenv("PROJECTDAVID_BASE_URL", "http://fastapi_cosmic_catalyst:9000")
        client = Entity(base_url=base_url)
        self.logging_utility.info(f"[{execution_id}] Initializing ProjectDavid client with base URL: {base_url}")

        # Ensure user exists (consider fetching existing user if appropriate)
        try:
            # Using a fixed name for simplicity, replace with actual user management if needed
            user_name = f"code_exec_{user_id}"
            # Try fetching first, then create if not found (more robust)
            existing_users = client.users.list_users(name=user_name)
            if existing_users:
                 user = existing_users[0]
                 self.logging_utility.info(f"[{execution_id}] Found existing user '{user_name}' with ID: {user.id}")
            else:
                 user = client.users.create_user(name=user_name)
                 self.logging_utility.info(f"[{execution_id}] Created user '{user_name}' with ID: {user.id}")

        except Exception as e:
            self.logging_utility.error(f"[{execution_id}] Failed to get or create user '{user_name}': {str(e)}")
            # Optionally: raise exception or return empty list? Returning empty for now.
            return uploaded_files

        async def upload_single_file(filename, file_path, user_obj):
            try:
                self.logging_utility.info(f"[{execution_id}] Attempting to upload file: {filename} from {file_path}")
                # Use the user object obtained earlier
                upload = client.files.upload_file(
                    file_path=file_path, user_id=user_obj.id, purpose="assistants_output" # Use specific purpose
                )
                self.logging_utility.info(f"[{execution_id}] Successfully uploaded {filename} (File ID: {upload.id})")

                # Get a shareable URL (consider if signed URL is needed or direct ID is enough)
                # Using get_file for details might be sufficient if URL isn't directly needed by user
                file_details = client.files.get_file(upload.id)

                # Return relevant details
                return {"filename": file_details.filename, "id": file_details.id, "size": file_details.bytes}
            except Exception as e:
                self.logging_utility.error(f"[{execution_id}] Upload failed for {filename}: {str(e)}", exc_info=True)
                return None

        tasks = []
        files_to_process = []
        try:
            files_to_process = os.listdir(self.generated_files_dir)
        except FileNotFoundError:
            self.logging_utility.warning(f"[{execution_id}] Generated files directory not found: {self.generated_files_dir}")
            return [] # Nothing to upload or clean up

        for fname in files_to_process:
            fpath = os.path.join(self.generated_files_dir, fname)
            # Skip directories (like mplcache) and the script itself
            if os.path.isfile(fpath):
                 is_script_file = False
                 if self.last_executed_script_path:
                     try:
                         # Use samefile for reliable comparison across OS
                         is_script_file = os.path.samefile(fpath, self.last_executed_script_path)
                     except FileNotFoundError:
                          pass # Script might have been deleted already
                     except Exception as sf_err:
                          self.logging_utility.warning(f"[{execution_id}] Error comparing file paths '{fpath}' and '{self.last_executed_script_path}': {sf_err}")

                 if not is_script_file:
                     tasks.append(upload_single_file(fname, fpath, user))
                 else:
                     self.logging_utility.debug(f"[{execution_id}] Skipping upload for executed script file: {fname}")


        if tasks:
             self.logging_utility.info(f"[{execution_id}] Gathering {len(tasks)} file upload tasks.")
             results = await asyncio.gather(*tasks, return_exceptions=True)

             for res in results:
                 if isinstance(res, dict) and res is not None:
                     uploaded_files.append(res)
                 elif isinstance(res, Exception):
                      self.logging_utility.error(f"[{execution_id}] Exception during file upload gather: {res}")
             self.logging_utility.info(f"[{execution_id}] Upload tasks complete. {len(uploaded_files)} files successfully uploaded.")
        else:
             self.logging_utility.info(f"[{execution_id}] No files found to upload (excluding script).")


        # --- Cleanup Generated Files ---
        self.logging_utility.info(f"[{execution_id}] Cleaning up generated files directory: {self.generated_files_dir}")
        cleaned_count = 0
        error_count = 0
        items_in_dir = []
        try:
            items_in_dir = os.listdir(self.generated_files_dir)
        except FileNotFoundError:
             self.logging_utility.debug(f"[{execution_id}] Generated files directory already gone during cleanup.")
             items_in_dir = [] # Avoid error later

        for item_name in items_in_dir:
            item_path = os.path.join(self.generated_files_dir, item_name)
            try:
                if os.path.isfile(item_path):
                    os.remove(item_path)
                    cleaned_count += 1
                    self.logging_utility.debug(f"[{execution_id}] Removed file: {item_path}")
                elif os.path.isdir(item_path):
                     # Decide whether to remove directories like mplcache or keep them
                     # For now, let's remove mplcache if it's empty, but be cautious
                     if item_name == "mplcache": # Specifically target mplcache
                          try:
                              os.rmdir(item_path) # Fails if not empty
                              cleaned_count += 1
                              self.logging_utility.debug(f"[{execution_id}] Removed directory: {item_path}")
                          except OSError:
                              self.logging_utility.warning(f"[{execution_id}] Could not remove directory {item_path} (likely not empty). Manual cleanup might be needed.")
                     # else: # Skip other directories
                     #    self.logging_utility.debug(f"[{execution_id}] Skipping directory cleanup for: {item_path}")

            except Exception as e:
                error_count += 1
                self.logging_utility.error(f"[{execution_id}] Cleanup failed for {item_path}: {str(e)}")

        self.logging_utility.info(f"[{execution_id}] Cleanup complete. Removed {cleaned_count} items, encountered {error_count} errors.")

        return uploaded_files
