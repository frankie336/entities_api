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


# In CodeExecutionMixin:
# from entities_api.utils.async_to_sync import async_to_sync_stream # Ensure this is available


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
        LOG.info(
            f"Run {run_id}: Starting code execution streaming for code interpreter..."
        )
        try:
            # ASSUMPTION: self.code_execution_client.stream_output IS AN ASYNC GENERATOR
            # You need an async_to_sync_stream or similar to consume it here.
            # If it's already a sync generator, this part is fine.

            # If self.code_execution_client.stream_output is async:
            # execution_stream_async = self.code_execution_client.stream_output(code)
            # for chunk_str in async_to_sync_stream(execution_stream_async): # Bridge to sync

            # If self.code_execution_client.stream_output is ALREADY SYNC:
            # The original loop is correct. The problem might be downstream or in async_to_sync_stream itself.

            execution_chunks = []
            # THIS IS THE CRITICAL PART: How is stream_output implemented?
            # For now, let's assume it's a sync generator. If it's async, the "Event loop is closed"
            # makes sense if async_to_sync_stream in the outer call closed it before this could run,
            # OR if stream_output() itself tries to manage an event loop badly.

            for chunk_str in self.code_execution_client.stream_output(
                code
            ):  # Assuming sync for now
                execution_chunks.append(chunk_str)

            for chunk_str in execution_chunks:
                try:
                    parsed_wrapper = json.loads(chunk_str)
                    # Ensure we handle both wrapped and unwrapped chunks
                    if (
                        isinstance(parsed_wrapper, dict)
                        and "stream_type" in parsed_wrapper
                        and "chunk" in parsed_wrapper
                    ):
                        parsed = parsed_wrapper["chunk"]
                        yield chunk_str  # Yield the original wrapped string
                    elif isinstance(parsed_wrapper, dict):  # It's an unwrapped chunk
                        parsed = parsed_wrapper
                        # Wrap it for consistency if consumers expect it
                        yield json.dumps(
                            {"stream_type": "code_execution", "chunk": parsed}
                        )
                    else:  # Not a dictionary, unexpected format
                        LOG.error(
                            f"Run {run_id}: Unexpected chunk format (not a dict): {chunk_str}"
                        )
                        # Yield an error chunk
                        yield json.dumps(
                            {
                                "stream_type": "code_execution",
                                "chunk": {
                                    "type": "error",
                                    "content": "Received malformed data from code execution.",
                                },
                            }
                        )
                        continue  # Skip further processing of this chunk

                    # Ensure 'parsed' is a dictionary before .get()
                    if not isinstance(parsed, dict):
                        LOG.error(f"Run {run_id}: Parsed chunk is not a dict: {parsed}")
                        continue

                    chunk_type = parsed.get("type")
                    content = parsed.get("content")

                    if chunk_type == "status":
                        status = content
                        LOG.debug(f"Run {run_id}: Code exec status: {status}")
                        if status == "complete" and "uploaded_files" in parsed:
                            uploaded_files.extend(parsed.get("uploaded_files", []))
                            LOG.info(
                                f"Run {run_id}: Execution complete; files metadata: {parsed.get('uploaded_files', [])}"
                            )
                        elif status == "process_complete":
                            LOG.info(
                                f"Run {run_id}: Process completed with exit code: {parsed.get('exit_code')}"
                            )

                    elif chunk_type == "hot_code_output":
                        hot_code_buffer.append(str(content))  # Ensure content is string

                    elif chunk_type == "error":
                        LOG.error(
                            f"Run {run_id}: Error chunk during execution: {content}"
                        )
                        hot_code_buffer.append(f"[Code Execution Error: {content}]")

                except json.JSONDecodeError:
                    LOG.error(
                        f"Run {run_id}: Invalid JSON chunk from code exec: {chunk_str}"
                    )
                    yield json.dumps(
                        {
                            "stream_type": "code_execution",
                            "chunk": {
                                "type": "error",
                                "content": "Received invalid JSON from code execution.",
                            },
                        }
                    )
                except Exception as e:
                    LOG.error(
                        f"Run {run_id}: Error processing code execution chunk: {e} – Chunk: {chunk_str}",
                        exc_info=True,
                    )
                    yield json.dumps(
                        {
                            "stream_type": "code_execution",
                            "chunk": {
                                "type": "error",
                                "content": f"Internal error processing code exec chunk: {e}",
                            },
                        }
                    )

        except (
            Exception
        ) as stream_err:  # This catches errors from self.code_execution_client.stream_output() itself
            LOG.error(
                f"Run {run_id}: Code execution streaming error: {stream_err}",
                exc_info=True,
            )
            # This is the error message shown in the UI.
            yield json.dumps(
                {
                    "stream_type": "code_execution",
                    "chunk": {
                        "type": "error",
                        "content": f"Failed to stream code execution: {stream_err}",
                    },
                }
            )
            # Ensure cleanup or alternative flow if streaming fails critically
            uploaded_files = []  # Reset uploaded_files as stream failed
            # Consider if final_content_for_assistant should reflect this error too.
            final_content_for_assistant = (
                f"[Error during code execution streaming: {stream_err}]"
            )

        # -------------------------------
        # Step 2: Build final content from code buffer
        # -------------------------------
        LOG.info(f"Run {run_id}: Building final content from code output buffer...")
        if hot_code_buffer:
            final_content_for_assistant = "\n".join(hot_code_buffer).strip()
        elif (
            not uploaded_files and not final_content_for_assistant
        ):  # Only if no output AND no files AND no stream error already set
            final_content_for_assistant = (
                "[Code executed successfully, no output and no files generated.]"
            )
        elif uploaded_files and not final_content_for_assistant:
            final_content_for_assistant = (
                "[Code executed successfully, files generated but no textual output.]"
            )

        # -------------------------------
        # Step 3: Stream base64 previews
        # -------------------------------
        if uploaded_files:
            LOG.info(
                f"Run {run_id}: Streaming base64 previews for {len(uploaded_files)} files..."
            )
            for file_meta in uploaded_files:
                file_id = file_meta.get("id")
                filename = file_meta.get("filename")
                if not file_id or not filename:
                    LOG.warning(
                        f"Run {run_id}: Skipping file with missing id or filename: {file_meta}"
                    )
                    continue

                guessed_mime, _ = mimetypes.guess_type(filename)
                mime_type = guessed_mime or "application/octet-stream"
                try:
                    b64 = self.project_david_client.files.get_file_as_base64(
                        file_id=file_id
                    )
                except Exception as e:
                    LOG.error(
                        f"Run {run_id}: Error fetching base64 for {filename} (ID: {file_id}): {e}",
                        exc_info=True,
                    )
                    b64 = base64.b64encode(
                        f"Error retrieving content for {filename}: {e}".encode()
                    ).decode()
                    mime_type = "text/plain"  # Indicate error by changing mime type

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
        LOG.info(f"Run {run_id}: Yielding final content chunk for code execution.")
        yield json.dumps(
            {
                "stream_type": "code_execution",  # This ensures it's identified as from code exec
                "chunk": {"type": "content", "content": final_content_for_assistant},
            }
        )

        # -------------------------------
        # Step 5: Debug log uploaded_files metadata
        # -------------------------------
        if uploaded_files:
            LOG.info(
                f"Run {run_id}: Final uploaded_files metadata:\n{pprint.pformat(uploaded_files)}"
            )

        # -------------------------------
        # Step 6: Submit only text output to assistant
        # -------------------------------
        try:
            LOG.info(
                f"Run {run_id}: Submitting text-only output to assistant: '{final_content_for_assistant[:100]}...'"
            )
            self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                content=final_content_for_assistant,  # Send the summary
                action=action,  # The action object created earlier
            )
            LOG.info(f"Run {run_id}: Tool output submitted successfully.")
        except Exception as submit_err:
            LOG.error(
                f"Run {run_id}: Error submitting tool output: {submit_err}",
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
