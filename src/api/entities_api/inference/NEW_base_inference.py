from abc import ABC, abstractmethod
from functools import lru_cache
from typing import Any, Dict, Generator, Optional

from .streamers import InferenceStreamer  # Assuming streamers are in a sub-module


class BaseInference(ABC):
    # ... (Keep __init__, properties for services, common helpers, FUNCTION CALL LOGIC) ...

    @lru_cache(maxsize=32)
    def _get_openai_client(
        self, api_key: Optional[str], base_url: Optional[str]
    ) -> OpenAI:
        # ... (Implementation as before: create/cache OpenAI clients) ...
        # Ensure base_url is part of the cache key implicitly or explicitly
        # Corrected version from previous steps should be fine here.
        # It *must* handle the case where api_key is None -> return default client or error.
        # It *must* handle the case where base_url is needed for specific client.
        if api_key:
            # If base_url is None here, use a default one for this provider type
            effective_base_url = base_url or "DEFAULT_PROVIDER_URL_IF_NEEDED"
            logging_utility.debug(
                f"Getting/Creating OpenAI client for key: ****, url: {effective_base_url}"
            )
            # ... creation logic ...
        else:
            # Return self.openai_client (the default one initialized in __init__)
            logging_utility.debug("Returning default OpenAI client.")
            if not self.openai_client:
                raise RuntimeError("Default client not initialized")
            return self.openai_client

    @abstractmethod
    def _get_streamer(self) -> InferenceStreamer:
        """Subclasses MUST implement this to return the correct streaming strategy."""
        pass

    def process_conversation(
        self,
        thread_id,
        message_id,  # Often unused if context builds full history
        run_id,
        assistant_id,
        model,
        stream_reasoning=False,  # May become config for the streamer
        api_key: Optional[str] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        """Orchestrates the streaming and function call processing."""

        self.start_cancellation_listener(run_id)
        accumulated_content = ""
        streamer = self._get_streamer()  # Get the right strategy

        try:
            # Prepare common details needed by the streamer
            messages = self._set_up_context_window(assistant_id, thread_id, trunk=True)
            request_details = {
                "model": model,
                "messages": messages,
                "stream_reasoning": stream_reasoning,  # Pass flag to streamer if it needs it
                # Add other common params like temperature if applicable
            }

            logging_utility.info(
                f"Run {run_id}: Starting stream via {type(streamer).__name__}"
            )

            # Delegate the actual streaming and initial parsing
            stream_generator = streamer.stream(
                request_details=request_details, api_key=api_key
            )

            for standardized_chunk in stream_generator:
                if self.check_cancellation_flag():
                    logging_utility.warning(
                        f"Run {run_id}: Cancellation detected during stream."
                    )
                    yield {"type": "error", "content": "Run cancelled"}
                    return  # Exit generation

                # Process the standardized chunk
                chunk_type = standardized_chunk.get("type")
                content = standardized_chunk.get("content", "")

                if chunk_type in [
                    "content",
                    "code_chunk",
                ]:  # Accumulate renderable content
                    accumulated_content += content
                elif chunk_type == "error":
                    logging_utility.error(
                        f"Run {run_id}: Error chunk received from streamer: {content}"
                    )
                    # Potentially handle error differently before yielding

                # Yield the standardized chunk (or reformat for SSE if needed here)
                yield standardized_chunk  # Assume downstream handles SSE wrapping for now

        except Exception as stream_err:
            logging_utility.error(
                f"Run {run_id}: Error during streamer execution: {stream_err}",
                exc_info=True,
            )
            yield {
                "type": "error",
                "content": f"Stream processing failed: {stream_err}",
            }
            self.handle_error(
                accumulated_content, thread_id, assistant_id, run_id
            )  # Save partial on error
            return  # Stop

        # --- Post-Streaming Logic ---
        logging_utility.info(
            f"Run {run_id}: Stream finished. Accumulated content length: {len(accumulated_content)}"
        )

        try:
            # Call the NON-NEGOTIABLE function call parsing
            if accumulated_content:
                # Pass accumulated content for function call parsing
                # Adjust 'assistant_reply' if it should be different from accumulated_content
                self.parse_and_set_function_calls(
                    accumulated_content, accumulated_content
                )

            # Call the NON-NEGOTIABLE function call execution/processing
            if self.get_function_call_state():
                logging_utility.info(
                    f"Run {run_id}: Processing detected function call state."
                )
                # Pass api_key if sub-calls might need it (like stream_function_call_output -> stream_hyperbolic)
                for func_chunk in self.process_function_calls(
                    thread_id, run_id, assistant_id, model, api_key=api_key
                ):
                    yield func_chunk  # Yield chunks from function processing/response
            else:
                # Finalize normally if no function call detected/processed
                if assistant_reply and hasattr(
                    self, "finalize_conversation"
                ):  # Use accumulated?
                    self.finalize_conversation(
                        accumulated_content, thread_id, assistant_id, run_id
                    )
                # Update status - careful not to override requires_action
                if hasattr(self, "run_service") and hasattr(validator, "StatusEnum"):
                    current_status = self.run_service.retrieve_run(
                        run_id
                    ).status  # Check current status
                    if current_status not in [
                        validator.StatusEnum.pending_action,
                        validator.StatusEnum.cancelling,
                        validator.StatusEnum.cancelled,
                        validator.StatusEnum.failed,
                        validator.StatusEnum.expired,
                    ]:
                        self.run_service.update_run_status(
                            run_id, validator.StatusEnum.completed
                        )

        except Exception as post_stream_err:
            logging_utility.error(
                f"Run {run_id}: Error during post-stream processing: {post_stream_err}",
                exc_info=True,
            )
            yield {
                "type": "error",
                "content": f"Post-stream processing failed: {post_stream_err}",
            }
            # Ensure status is set to failed
            if hasattr(self, "run_service"):
                self.run_service.update_run_status(run_id, validator.StatusEnum.failed)
