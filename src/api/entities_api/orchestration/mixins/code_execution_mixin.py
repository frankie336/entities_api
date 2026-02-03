# src/api/entities_api/orchestration/mixins/code_execution_mixin.py
from __future__ import annotations

import asyncio
import json
import mimetypes
import re
from typing import Any, AsyncGenerator, Dict, List, Optional

from src.api.entities_api.services.logging_service import LoggingUtility

LOG = LoggingUtility()


class CodeExecutionMixin:
    """
    Mixin that handles the `code_interpreter` tool from registration,
    through real-time streaming, to final summary/attachment handling.

    Level 2 Enhancement: Implementation of automated self-correction for
    code failures (SyntaxErrors, RuntimeErrors, etc.).
    """

    @staticmethod
    def _format_level2_code_error(error_content: str) -> str:
        """
        Translates raw Python execution errors into actionable hints for the LLM.
        """
        return (
            f"Code Execution Failed: {error_content}\n\n"
            "Instructions: Please analyze the traceback above. If this is a syntax error, "
            "logical bug, or missing import, correct your code and retry execution. "
            "If a data file was missing, ensure you used the correct file path from the context."
        )

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

        # 2. Create the Action Record
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

        # ⚡ HOT CODE REPLAY (Visual feedback)
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
            sync_iter = iter(self.code_execution_client.stream_output(code))

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

                            # Detection of failure within the stream
                            if (
                                "Traceback" in clean_content
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
                        yield json.dumps(
                            {"stream_type": "code_execution", "chunk": payload}
                        )

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
            # LEVEL 2: Instead of raw failure, we provide a structured Hint
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
                unsent_buffer.replace("\\n", "\n")
                .replace('\\"', '"')
                .replace("\\'", "'")
            )
            if len(clean_segment) == 1 and clean_segment in ('"', "}"):
                return start_index, cursor, None
            payload_dict = {"type": "hot_code", "content": clean_segment}
            self._shunt_to_redis_stream(redis_client, stream_key, payload_dict)
            return start_index, cursor, json.dumps(payload_dict)

        return start_index, cursor, None
