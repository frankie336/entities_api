# src/api/entities_api/orchestration/mixins/code_execution_mixin.py
from __future__ import annotations

import asyncio
import json
import mimetypes
from typing import Any, AsyncGenerator, Dict, List, Optional

from src.api.entities_api.services.logging_service import LoggingUtility

LOG = LoggingUtility()


class CodeExecutionMixin:
    """
    Mixin that handles the `code_interpreter` tool from registration,
    through real-time streaming, to final summary/attachment handling.
    """

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

        # 2. Create the Action Record (Keyword args prevent positional swap bugs)
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

        # ⚡ HOT CODE REPLAY
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

        # 3. Stream Execution Output
        try:
            sync_iter = iter(self.code_execution_client.stream_output(code))

            # FIX: safe_next wrapper catches StopIteration inside the thread
            # so it doesn't crash the asyncio Future.
            def safe_next(it):
                try:
                    return next(it)
                except (StopIteration, Exception):
                    return None

            while True:
                # Offload to thread using safe wrapper
                chunk_str = await asyncio.to_thread(safe_next, sync_iter)

                # If None, stream ended (StopIteration) or client disconnected
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
                        LOG.error(f"CodeInterpreter ▸ Error: {content}")
                        hot_code_buffer.append(f"[Code Exec Error] {content}")
                        yield json.dumps(
                            {
                                "stream_type": "code_execution",
                                "chunk": {"type": "error", "content": content},
                            }
                        )

        except Exception as stream_err:
            LOG.error(f"CodeInterpreter ▸ Stream error: {stream_err}")
            yield json.dumps(
                {
                    "type": "error",
                    "chunk": {"type": "error", "content": str(stream_err)},
                }
            )

        # 4. Final Summary Construction
        final_content = (
            "\n".join(hot_code_buffer).strip() or "[Code executed successfully.]"
        )

        # 5. Process Files
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

        # 6. Close out
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
        try:
            await self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                content=final_content,
                action=action,
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
