from __future__ import annotations

import base64
import json
import mimetypes
import pprint
from typing import Generator, List

from src.api.entities_api.services.logging_service import LoggingUtility

LOG = LoggingUtility()


class CodeExecutionMixin:
    """
    Mixin that handles the `code_interpreter` tool from registration,
    through real-time streaming, to final summary/attachment handling.
    """

    def handle_code_interpreter_action(
        self, thread_id: str, run_id: str, assistant_id: str, arguments_dict: dict
    ) -> Generator[str, None, None]:
        """
        Streams sandbox output **live** while accumulating a plain-text
        summary and optional file previews.
        """
        yield json.dumps(
            {
                "stream_type": "code_execution",
                "chunk": {"type": "status", "status": "started", "run_id": run_id},
            }
        )
        action = self.project_david_client.actions.create_action(
            tool_name="code_interpreter", run_id=run_id, function_args=arguments_dict
        )
        code: str = arguments_dict.get("code", "")
        uploaded_files: List[dict] = []
        hot_code_buffer: List[str] = []
        final_content_for_assistant = ""
        LOG.info("Run %s: streaming sandbox output…", run_id)
        try:
            for chunk_str in self.code_execution_client.stream_output(code):
                yield chunk_str
                try:
                    wrapper = json.loads(chunk_str)
                    payload = (
                        wrapper["chunk"]
                        if isinstance(wrapper, dict) and "chunk" in wrapper
                        else wrapper if isinstance(wrapper, dict) else None
                    )
                    if not isinstance(payload, dict):
                        continue
                    ctype = payload.get("type")
                    content = payload.get("content")
                    if ctype == "status":
                        status = content
                        LOG.debug("Run %s: sandbox status → %s", run_id, status)
                        if status == "complete" and isinstance(
                            payload.get("uploaded_files"), list
                        ):
                            uploaded_files.extend(payload["uploaded_files"])
                    elif ctype == "hot_code_output":
                        hot_code_buffer.append(str(content))
                    elif ctype == "error":
                        LOG.error("Run %s: sandbox error chunk: %s", run_id, content)
                        hot_code_buffer.append(f"[Code Exec Error] {content}")
                except json.JSONDecodeError:
                    LOG.warning(
                        "Run %s: non-JSON sandbox chunk ignored: %.120s",
                        run_id,
                        chunk_str,
                    )
                except Exception as e:
                    LOG.error(
                        "Run %s: error parsing sandbox chunk: %s",
                        run_id,
                        e,
                        exc_info=True,
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
            uploaded_files = []
            hot_code_buffer.append(f"[Streaming error] {stream_err}")
        if hot_code_buffer:
            final_content_for_assistant = "\n".join(hot_code_buffer).strip()
        elif not uploaded_files:
            final_content_for_assistant = (
                "[Code executed successfully, no output and no files generated.]"
            )
        else:
            final_content_for_assistant = (
                "[Code executed successfully, files generated but no textual output.]"
            )
        for file_meta in uploaded_files:
            file_id = file_meta.get("id")
            filename = file_meta.get("filename")
            if not file_id or not filename:
                LOG.warning(
                    "Run %s: skipping file with missing metadata: %s", run_id, file_meta
                )
                continue
            mime_type, _ = mimetypes.guess_type(filename)
            mime_type = mime_type or "application/octet-stream"
            try:
                b64 = self.project_david_client.files.get_file_as_base64(
                    file_id=file_id
                )
            except Exception as e:
                LOG.error(
                    "Run %s: error fetching file %s (%s): %s",
                    run_id,
                    filename,
                    file_id,
                    e,
                    exc_info=True,
                )
                b64 = base64.b64encode(
                    f"Error retrieving {filename}: {e}".encode()
                ).decode()
                mime_type = "text/plain"
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
        try:
            self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
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
