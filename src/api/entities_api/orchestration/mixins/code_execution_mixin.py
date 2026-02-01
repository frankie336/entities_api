# src/api/entities_api/orchestration/mixins/code_execution_mixin.py
from __future__ import annotations

import json
import mimetypes
import pprint
from typing import Any, Dict, Generator, List, Optional

from src.api.entities_api.services.logging_service import LoggingUtility

LOG = LoggingUtility()


class CodeExecutionMixin:
    """
    Mixin that handles the `code_interpreter` tool from registration,
    through real-time streaming, to final summary/attachment handling.
    """

    def handle_code_interpreter_action(
        self,
        thread_id: str,
        run_id: str,
        assistant_id: str,
        arguments_dict: dict,
        tool_call_id: Optional[str] = None,
        # [NEW] Accept decision payload
        decision: Optional[Dict] = None,
    ) -> Generator[str, None, None]:
        """
        Streams sandbox output **live** while accumulating a plain-text
        summary and optional file previews.
        """
        # 1. Notify start
        yield json.dumps(
            {
                "stream_type": "code_execution",
                "chunk": {"type": "status", "status": "started", "run_id": run_id},
            }
        )

        # 1. Create the Action Record with Decision Data
        action = self.project_david_client.actions.create_action(
            tool_name="code_interpreter",
            run_id=run_id,
            tool_call_id=tool_call_id,
            function_args=arguments_dict,
            # [NEW] Pass to API/Service
            decision=decision,
        )

        code: str = arguments_dict.get("code", "")

        # ---------------------------------------------------------
        # ⚡ HOT CODE REPLAY (Line-by-Line Typewriter)
        # ---------------------------------------------------------
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
        # ---------------------------------------------------------

        uploaded_files: List[dict] = []
        hot_code_buffer: List[str] = []
        final_content_for_assistant = ""
        LOG.info("Run %s: streaming sandbox output…", run_id)

        # Use a proper JSON decoder to handle split/merged packets
        decoder = json.JSONDecoder()
        stream_buffer = ""

        # 3. Stream Execution Output (Robust Parsing)
        try:
            for chunk_str in self.code_execution_client.stream_output(code):
                stream_buffer += chunk_str

                # Continuously decode valid objects from the buffer
                while stream_buffer:
                    stream_buffer = stream_buffer.lstrip()  # Remove leading whitespace
                    if not stream_buffer:
                        break

                    try:
                        # raw_decode returns the object and the index where it ended
                        wrapper, idx = decoder.raw_decode(stream_buffer)
                        # Slice off the processed part
                        stream_buffer = stream_buffer[idx:]
                    except json.JSONDecodeError:
                        # Not enough data for a full JSON object yet; wait for next chunk
                        break

                    # --- Process the Successfully Decoded Wrapper ---
                    payload = (
                        wrapper["chunk"]
                        if isinstance(wrapper, dict) and "chunk" in wrapper
                        else wrapper if isinstance(wrapper, dict) else None
                    )

                    if not isinstance(payload, dict):
                        continue

                    ctype = payload.get("type")
                    content = payload.get("content")

                    # --- OUTPUT HANDLER ---
                    if ctype in ("hot_code_output", "stdout", "stderr", "console"):
                        if content is not None:
                            clean_content = str(content)
                            # Backend sanitization replacing frontend helper
                            clean_content = clean_content.replace("\\n", "\n")

                            hot_code_buffer.append(clean_content)

                            yield json.dumps(
                                {
                                    "stream_type": "code_execution",
                                    "chunk": {
                                        "type": "hot_code_output",
                                        "content": clean_content,
                                    },
                                }
                            )

                    # --- STATUS HANDLER ---
                    elif ctype == "status":
                        status = content
                        LOG.debug("Run %s: sandbox status → %s", run_id, status)
                        if status == "complete" and isinstance(
                            payload.get("uploaded_files"), list
                        ):
                            uploaded_files.extend(payload["uploaded_files"])

                        yield json.dumps(
                            {"stream_type": "code_execution", "chunk": payload}
                        )

                    # --- ERROR HANDLER ---
                    elif ctype == "error":
                        LOG.error("Run %s: sandbox error chunk: %s", run_id, content)
                        hot_code_buffer.append(f"[Code Exec Error] {content}")
                        yield json.dumps(
                            {
                                "stream_type": "code_execution",
                                "chunk": {"type": "error", "content": content},
                            }
                        )

        except Exception as stream_err:
            LOG.error(
                "Run %s: sandbox streaming failed: %s",
                run_id,
                stream_err,
                exc_info=True,
            )
            yield json.dumps(
                {
                    "stream_type": "code_execution",
                    "chunk": {
                        "type": "error",
                        "content": f"Failed to stream code execution: {stream_err}",
                    },
                }
            )
            hot_code_buffer.append(f"[Streaming error] {stream_err}")

        # 4. Construct Final Summary for LLM
        if len(hot_code_buffer) > 0:
            final_content_for_assistant = "\n".join(hot_code_buffer).strip()
            if not final_content_for_assistant:
                final_content_for_assistant = (
                    "[Code executed successfully. Output contained only whitespace.]"
                )
        elif not uploaded_files:
            final_content_for_assistant = (
                "[Code executed successfully, no output and no files generated.]"
            )
        else:
            final_content_for_assistant = (
                "[Code executed successfully, files generated but no textual output.]"
            )

        # 5. Process and Yield Generated Files
        for file_meta in uploaded_files:
            file_id = file_meta.get("id")
            filename = file_meta.get("filename")
            if not file_id or not filename:
                continue

            mime_type, _ = mimetypes.guess_type(filename)
            mime_type = mime_type or "application/octet-stream"
            try:
                b64 = self.project_david_client.files.get_file_as_base64(
                    file_id=file_id
                )
            except Exception as e:
                LOG.error(f"Error fetching file {file_id}: {e}")
                b64 = ""

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

        # 6. Yield Final Content Summary
        yield json.dumps(
            {
                "stream_type": "code_execution",
                "chunk": {"type": "content", "content": final_content_for_assistant},
            }
        )
        yield json.dumps(
            {
                "stream_type": "code_execution",
                "chunk": {"type": "status", "status": "complete", "run_id": run_id},
            }
        )

        if uploaded_files:
            LOG.info(
                "Run %s: uploaded_files metadata:\n%s",
                run_id,
                pprint.pformat(uploaded_files),
            )

        # 7. Submit Output back to Thread/Assistant
        try:
            self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                content=final_content_for_assistant,
                action=action,
            )
            LOG.info("Run %s: tool output submitted.", run_id)
        except Exception as submit_err:
            LOG.error(
                "Run %s: error submitting tool output: %s",
                run_id,
                submit_err,
                exc_info=True,
            )
            yield json.dumps(
                {
                    "stream_type": "code_execution",
                    "chunk": {
                        "type": "error",
                        "content": f"Failed to submit results to assistant: {submit_err}",
                    },
                }
            )

    def process_hot_code_buffer(
        self,
        buffer: str,
        start_index: int,
        cursor: int,
        redis_client: Any,
        stream_key: str,
    ) -> tuple[int, int, Optional[str]]:
        """
        Process a raw JSON buffer to extract, clean, and stream code execution updates.
        Handles the 'Matrix effect' buffering to prevent one-char-per-line rendering issues.

        Args:
            buffer: The accumulated raw JSON string of arguments.
            start_index: The cached index where the code string starts (-1 if unknown).
            cursor: The number of characters from the code string already processed.
            redis_client: The Redis connection.
            stream_key: The Redis stream key.

        Returns:
            (new_start_index, new_cursor, json_payload_string_or_None)
        """
        import json
        import re

        # 1. Locate Start of Code (Once)
        if start_index == -1:
            # Matches keys like "code" or 'code' followed by colon and quote
            match = re.search(r"[\"\']code[\"\']\s*:\s*[\"\']", buffer)
            if match:
                start_index = match.end()
            else:
                # Code field not found yet
                return start_index, cursor, None

        # 2. Slice the relevant data
        full_code_value = buffer[start_index:]
        unsent_buffer = full_code_value[cursor:]

        if not unsent_buffer:
            return start_index, cursor, None

        # 3. Buffering Strategy (The Fix)
        # We buffer until we have a newline, a decent chunk size, or the end of the string.
        has_newline = "\\n" in unsent_buffer
        is_long_enough = len(unsent_buffer) > 15
        is_closed = unsent_buffer.endswith('"') or unsent_buffer.endswith("'")

        # Safety: Never cut on a backslash to protect escape sequences
        safe_cut = not unsent_buffer.endswith("\\")

        if (has_newline or is_long_enough or is_closed) and safe_cut:

            # Commit cursor forward
            cursor += len(unsent_buffer)

            # Visual De-escaping
            clean_segment = (
                unsent_buffer.replace("\\n", "\n")
                .replace('\\"', '"')
                .replace("\\'", "'")
            )

            # Squelch structural closers at the tail end (visual only)
            if len(clean_segment) == 1 and clean_segment in ('"', "}"):
                return start_index, cursor, None

            # Construct Payload
            payload_dict = {"type": "hot_code", "content": clean_segment}

            # Side-effect: Shunt to Redis immediately
            # (Assumes OrchestratorCore has _shunt_to_redis_stream, which is standard in your architecture)
            self._shunt_to_redis_stream(redis_client, stream_key, payload_dict)

            return start_index, cursor, json.dumps(payload_dict)

        # Not enough data to yield yet
        return start_index, cursor, None
