"""
CodeExecutionMixin
==================

Executes arbitrary code in the Project-David sandbox and streams **UI-ready SSE
JSON strings** in real time.

Workflow
--------
1. Register an authenticated `code_interpreter` Action.
2. Forward every raw chunk from `code_execution_client.stream_output()` directly
   to the frontend.
3. Collect stdout / stderr lines as a **plain-text** summary.
4. When the sandbox reports `status == "complete"`, fetch any `uploaded_files`
   and stream them back as Base-64 previews (`code_interpreter_stream` chunks).
5. Emit a final `content` chunk with the text summary.
6. Persist the summary into the thread via `submit_tool_output()`.

Error handling
--------------
• All parsing or network errors are surfaced as `"type": "error"` chunks.
• Detailed diagnostics are logged through :pyclass:`entities_api.services.logging_service.LoggingUtility`
  (referenced here as ``LOG``).

This implementation mirrors the original monolith’s behaviour while keeping
the streaming path fully transparent to the UI.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import pprint

# Use your LoggingUtility. I'll use `LOG` as the instance name.
from entities_api.services.logging_service import (
    LoggingUtility,
)  # Adjust path if necessary

LOG = LoggingUtility()


# logger = logging.getLogger(__name__) # If you also use standard module logger


class CodeExecutionMixin:
    """
    Provides code interpreter execution and streaming behavior,
    closely following the original monolith's logic, with added targeted debugging logs.
    """

    def handle_code_interpreter_action(
        self, thread_id, run_id, assistant_id, arguments_dict
    ):

        action = self.project_david_client.actions.create_action(
            tool_name="code_interpreter", run_id=run_id, function_args=arguments_dict
        )

        code = arguments_dict.get("code")

        uploaded_files = []
        hot_code_buffer = []
        final_content_for_assistant = ""

        # -------------------------------
        # Step 1: Stream raw code execution output as-is
        # -------------------------------
        LOG.info("Starting code execution streaming...")
        try:
            execution_chunks = []
            for chunk_str in self.code_execution_client.stream_output(code):
                execution_chunks.append(chunk_str)

            for chunk_str in execution_chunks:
                try:
                    parsed_wrapper = json.loads(chunk_str)
                    if "stream_type" in parsed_wrapper and "chunk" in parsed_wrapper:
                        parsed = parsed_wrapper["chunk"]
                        yield chunk_str
                    else:
                        parsed = parsed_wrapper
                        yield json.dumps(
                            {"stream_type": "code_execution", "chunk": parsed}
                        )

                    chunk_type = parsed.get("type")
                    content = parsed.get("content")

                    if chunk_type == "status":
                        status = content
                        LOG.debug("Status chunk: %s", status)
                        if status == "complete" and "uploaded_files" in parsed:
                            uploaded_files.extend(parsed.get("uploaded_files", []))
                            LOG.info(
                                "Execution complete; files metadata: %s",
                                parsed.get("uploaded_files", []),
                            )
                        elif status == "process_complete":
                            LOG.info(
                                "Process completed with exit code: %s",
                                parsed.get("exit_code"),
                            )

                    elif chunk_type == "hot_code_output":
                        hot_code_buffer.append(content)

                    elif chunk_type == "error":
                        LOG.error("Error chunk during execution: %s", content)
                        hot_code_buffer.append(f"[Code Execution Error: {content}]")

                except json.JSONDecodeError:
                    LOG.error("Invalid JSON chunk: %s", chunk_str)
                    yield json.dumps(
                        {
                            "stream_type": "code_execution",
                            "chunk": {
                                "type": "error",
                                "content": "Received invalid data from code execution.",
                            },
                        }
                    )
                except Exception as e:
                    LOG.error(
                        "Error processing execution chunk: %s – %s",
                        str(e),
                        chunk_str,
                        exc_info=True,
                    )
                    yield json.dumps(
                        {
                            "stream_type": "code_execution",
                            "chunk": {
                                "type": "error",
                                "content": f"Internal error: {str(e)}",
                            },
                        }
                    )

        except Exception as stream_err:
            LOG.error("Streaming error: %s", str(stream_err), exc_info=True)
            yield json.dumps(
                {
                    "stream_type": "code_execution",
                    "chunk": {
                        "type": "error",
                        "content": f"Failed to stream code execution: {str(stream_err)}",
                    },
                }
            )
            uploaded_files = []

        # -------------------------------
        # Step 2: Build final content from code buffer (suppress markdown)
        # -------------------------------
        LOG.info("Building final content from code output buffer...")
        if hot_code_buffer:
            final_content_for_assistant = "\n".join(hot_code_buffer).strip()
        else:
            final_content_for_assistant = "[Code executed successfully, no output.]"

        # -------------------------------
        # Step 3: Stream base64 previews (unchanged)
        # -------------------------------
        if uploaded_files:
            LOG.info("Streaming base64 previews for %d files...", len(uploaded_files))
            for file_meta in uploaded_files:
                file_id = file_meta.get("id")
                filename = file_meta.get("filename")
                if not file_id or not filename:
                    continue

                guessed_mime, _ = mimetypes.guess_type(filename)
                mime_type = guessed_mime or "application/octet-stream"
                try:

                    b64 = self.project_david_client.files.get_file_as_base64(
                        file_id=file_id
                    )

                except Exception as e:
                    LOG.error(
                        "Error fetching base64 for %s: %s",
                        filename,
                        str(e),
                        exc_info=True,
                    )
                    b64 = base64.b64encode(
                        f"Error retrieving content: {str(e)}".encode()
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

        # -------------------------------
        # Step 4: Final frontend-visible chunk
        # -------------------------------
        LOG.info("Yielding final content chunk.")
        yield json.dumps(
            {
                "stream_type": "code_execution",
                "chunk": {"type": "content", "content": final_content_for_assistant},
            }
        )

        # -------------------------------
        # Step 5: Debug log uploaded_files metadata
        # -------------------------------
        LOG.info("Final uploaded_files metadata:\n%s", pprint.pformat(uploaded_files))

        # -------------------------------
        # Step 6: Submit only text output to assistant
        # -------------------------------
        try:
            LOG.info("Submitting text-only output to assistant.")
            self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                content=final_content_for_assistant,
                action=action,
            )
            LOG.info("Tool output submitted successfully.")
        except Exception as submit_err:
            LOG.error(
                "Error submitting tool output: %s", str(submit_err), exc_info=True
            )
            yield json.dumps(
                {
                    "stream_type": "code_execution",
                    "chunk": {
                        "type": "error",
                        "content": f"Failed to submit results: {str(submit_err)}",
                    },
                }
            )
