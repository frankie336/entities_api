# src/api/entities_api/orchestration/mixins/code_execution_mixin.py

from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import re
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

import jwt
from projectdavid_common import ToolValidator

from src.api.entities_api.services.logging_service import LoggingUtility

LOG = LoggingUtility()


class CodeExecutionMixin:
    """
    Mixin that handles the `code_interpreter` tool.

    Level 2 Enhancements:
    1. Shared Input Validation: Rejects malformed JSON via shared ToolValidator before execution.
    2. Runtime Correction: Catches Python exceptions and prompts for fixes (Self-Correction).
    3. Secured Execution: Generates short-lived JWTs to authorize Sandbox access.
    """

    @staticmethod
    def _format_level2_code_error(error_content: str) -> str:
        """
        Translates execution errors into actionable hints for the LLM.
        """
        return (
            f"Code Execution Failed: {error_content}\n\n"
            "Instructions: Please analyze the traceback above. If this is a syntax error, "
            "logical bug, or missing import, correct your code and retry execution. "
            "If a data file was missing, ensure you used the correct file path from the context."
        )

    def _generate_sandbox_token(self, subject_id: str) -> str:
        """
        Generates a short-lived JWT to authorize the connection to the Sandbox API.
        """
        secret = os.getenv("SANDBOX_AUTH_SECRET")
        if not secret:
            LOG.error("CRITICAL: SANDBOX_AUTH_SECRET is missing in environment variables.")
            raise ValueError("Server configuration error: Sandbox secret missing.")

        payload = {
            "sub": subject_id,
            "iat": int(time.time()),
            "exp": int(time.time()) + 60,  # Token valid for 60 seconds (connection setup only)
            "scopes": ["execution"],
        }

        # Generates a token signed with HS256
        return jwt.encode(payload, secret, algorithm="HS256")

    async def handle_code_interpreter_action(
        self,
        thread_id: str,
        run_id: str,
        assistant_id: str,
        arguments_dict: dict,
        tool_call_id: Optional[str] = None,
        decision: Optional[Dict] = None,
    ) -> AsyncGenerator[str, None]:

        # 1. Notify start
        yield json.dumps(
            {
                "stream_type": "code_execution",
                "chunk": {"type": "status", "status": "started", "run_id": run_id},
            }
        )

        # --- [L2] SHARED INPUT VALIDATION ---
        # Instantiate validator and manually enforce schema for this platform tool.
        # This replaces the standalone validate_code_payload function.
        validator = ToolValidator()
        validator.schema_registry = {"code_interpreter": ["code"]}

        # validate_args returns an error string if invalid, or None if valid
        validation_error = validator.validate_args("code_interpreter", arguments_dict)
        is_valid = validation_error is None

        if not is_valid:
            LOG.warning(f"CodeInterpreter ▸ Validation Failed: {validation_error}")

            # Create a failed action record for history tracking
            try:
                action = await asyncio.to_thread(
                    self.project_david_client.actions.create_action,
                    tool_name="code_interpreter",
                    run_id=run_id,
                    tool_call_id=tool_call_id,
                    function_args=arguments_dict,
                    decision=decision,
                )
            except Exception:
                pass

            # Send the Validation Error directly back to the LLM
            error_msg = (
                f"{validation_error}\n" "Please correct the function arguments and try again."
            )

            # Stream the error to frontend
            yield json.dumps(
                {
                    "stream_type": "code_execution",
                    "chunk": {"type": "error", "content": validation_error},
                }
            )

            # Submit to Orchestrator as an error result to trigger Turn 2
            await self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                content=error_msg,
                action=action if "action" in locals() else None,
                is_error=True,  # <--- CRITICAL: Flags the orchestrator to loop back
            )
            return
        # -----------------------------

        # 2. Create the Action Record (DB)
        try:
            action = await asyncio.to_thread(
                self.project_david_client.actions.create_action,
                tool_name="code_interpreter",
                run_id=run_id,
                tool_call_id=tool_call_id,
                function_args=arguments_dict,
                decision=decision,
            )
        except Exception as e:
            LOG.error(f"CodeInterpreter ▸ Action creation failed: {e}")
            yield json.dumps(
                {
                    "type": "error",
                    "chunk": {"type": "error", "content": f"Creation failed: {e}"},
                }
            )
            return

        code: str = arguments_dict.get("code", "")

        # ⚡ HOT CODE REPLAY (Visual Matrix Effect)
        if code:
            yield json.dumps(
                {
                    "stream_type": "code_execution",
                    "chunk": {"type": "hot_code", "content": "```python\n"},
                }
            )

            for line in code.splitlines(keepends=True):
                yield json.dumps(
                    {
                        "stream_type": "code_execution",
                        "chunk": {"type": "hot_code", "content": line},
                    }
                )
            yield json.dumps(
                {
                    "stream_type": "code_execution",
                    "chunk": {"type": "hot_code", "content": "\n```\n"},
                }
            )

        uploaded_files: List[dict] = []
        hot_code_buffer: List[str] = []
        decoder = json.JSONDecoder()
        stream_buffer = ""
        execution_had_error = False

        # 3. Stream Execution Output
        try:
            # --- [SECURE] Generate Auth Token ---
            # We use the run_id as the identity for the sandbox logs
            auth_token = self._generate_sandbox_token(subject_id=f"run_{run_id}")

            # Pass the token to the client method
            sync_iter = iter(self.code_execution_client.stream_output(code, token=auth_token))

            def safe_next(it):
                try:
                    return next(it)
                except (StopIteration, Exception):
                    return None

            while True:
                chunk_str = await asyncio.to_thread(safe_next, sync_iter)
                if chunk_str is None:
                    break

                stream_buffer += chunk_str

                while stream_buffer:
                    stream_buffer = stream_buffer.lstrip()
                    if not stream_buffer:
                        break
                    try:
                        wrapper, idx = decoder.raw_decode(stream_buffer)
                        stream_buffer = stream_buffer[idx:]
                    except json.JSONDecodeError:
                        break

                    payload = (
                        wrapper["chunk"]
                        if isinstance(wrapper, dict) and "chunk" in wrapper
                        else wrapper if isinstance(wrapper, dict) else None
                    )

                    if not isinstance(payload, dict):
                        continue

                    ctype = payload.get("type")
                    content = payload.get("content")

                    if ctype in ("hot_code_output", "stdout", "stderr", "console"):
                        if content is not None:
                            clean_content = str(content).replace("\\n", "\n")
                            hot_code_buffer.append(clean_content)

                            # [L2] Detection of failure within the stream
                            if (
                                ctype == "stderr"
                                or "Traceback" in clean_content
                                or "Error:" in clean_content
                            ):
                                execution_had_error = True

                            yield json.dumps(
                                {
                                    "stream_type": "code_execution",
                                    "chunk": {
                                        "type": "hot_code_output",
                                        "content": clean_content,
                                    },
                                }
                            )

                    elif ctype == "status":
                        if content == "complete" and isinstance(
                            payload.get("uploaded_files"), list
                        ):
                            uploaded_files.extend(payload["uploaded_files"])
                        yield json.dumps({"stream_type": "code_execution", "chunk": payload})

                    elif ctype == "error":
                        execution_had_error = True
                        LOG.error(f"CodeInterpreter ▸ Error: {content}")
                        hot_code_buffer.append(f"[Code Exec Error] {content}")
                        yield json.dumps(
                            {
                                "stream_type": "code_execution",
                                "chunk": {"type": "error", "content": content},
                            }
                        )

        except Exception as stream_err:
            execution_had_error = True
            LOG.error(f"CodeInterpreter ▸ Stream error: {stream_err}")
            yield json.dumps(
                {
                    "type": "error",
                    "chunk": {"type": "error", "content": str(stream_err)},
                }
            )

        # 4. Final Summary & Level 2 Correction Logic
        raw_output = "\n".join(hot_code_buffer).strip()

        if execution_had_error:
            # [L2] Instead of raw failure, we provide a structured Hint
            final_content = self._format_level2_code_error(
                raw_output or "Unknown execution failure."
            )
            LOG.warning(f"CodeInterpreter ▸ Self-Correction Triggered for run {run_id}")
        else:
            final_content = raw_output or "[Code executed successfully.]"

        # 5. Process Files (Plots/CSVs generated during execution)
        for file_meta in uploaded_files:
            file_id, filename = file_meta.get("id"), file_meta.get("filename")
            if not file_id or not filename:
                continue
            mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            try:
                b64 = await asyncio.to_thread(
                    self.project_david_client.files.get_file_as_base64, file_id=file_id
                )
                yield json.dumps(
                    {
                        "stream_type": "code_execution",
                        "chunk": {
                            "type": "code_interpreter_stream",
                            "content": {
                                "filename": filename,
                                "file_id": file_id,
                                "base64": b64,
                                "mime_type": mime_type,
                            },
                        },
                    }
                )
            except Exception as e:
                LOG.error(f"CodeInterpreter ▸ File fetch error ({file_id}): {e}")

        # 6. Close out current stream
        yield json.dumps(
            {
                "stream_type": "code_execution",
                "chunk": {"type": "content", "content": final_content},
            }
        )
        yield json.dumps(
            {
                "stream_type": "code_execution",
                "chunk": {"type": "status", "status": "complete", "run_id": run_id},
            }
        )

        # 7. Submit Result (Awaiting async submit)
        # On error, is_error=True signals the orchestrator that Turn 2 is required
        try:
            await self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                content=final_content,
                action=action,
                is_error=execution_had_error,
            )
        except Exception as e:
            LOG.error(f"CodeInterpreter ▸ Submission failure: {e}")

    def process_hot_code_buffer(
        self,
        buffer: str,
        start_index: int,
        cursor: int,
        redis_client: Any,
        stream_key: str,
    ) -> tuple[int, int, Optional[str]]:
        """
        Process raw JSON buffer for 'Matrix effect' rendering.
        """
        if start_index == -1:
            match = re.search(r"[\"\']code[\"\']\s*:\s*[\"\']", buffer)
            if match:
                start_index = match.end()
            else:
                return start_index, cursor, None

        full_code_value = buffer[start_index:]
        unsent_buffer = full_code_value[cursor:]
        if not unsent_buffer:
            return start_index, cursor, None

        has_newline = "\\n" in unsent_buffer
        is_long_enough = len(unsent_buffer) > 15
        is_closed = unsent_buffer.endswith('"') or unsent_buffer.endswith("'")
        safe_cut = not unsent_buffer.endswith("\\")

        if (has_newline or is_long_enough or is_closed) and safe_cut:
            cursor += len(unsent_buffer)
            clean_segment = (
                unsent_buffer.replace("\\n", "\n").replace('\\"', '"').replace("\\'", "'")
            )
            if len(clean_segment) == 1 and clean_segment in ('"', "}"):
                return start_index, cursor, None
            payload_dict = {"type": "hot_code", "content": clean_segment}
            # Optional: self._shunt_to_redis_stream(redis_client, stream_key, payload_dict)
            return start_index, cursor, json.dumps(payload_dict)

        return start_index, cursor, None
