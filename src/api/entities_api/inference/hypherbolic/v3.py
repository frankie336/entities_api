import json
import sys
import time
from typing import Optional

from dotenv import load_dotenv

from entities_api.inference.base_inference import BaseInference
from entities_api.services.logging_service import LoggingUtility

load_dotenv()
logging_utility = LoggingUtility()


class HyperbolicV3Inference(BaseInference):

    def setup_services(self):
        logging_utility.debug(
            "HyperbolicV3Inference specific setup completed (if any)."
        )

    def stream_function_call_output(
        self,
        thread_id,
        run_id,
        assistant_id,
        model,
        name=None,
        stream_reasoning=False,
        api_key: Optional[str] = None,
    ):

        return super().stream_function_call_output(
            thread_id=thread_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            stream_reasoning=stream_reasoning,
            api_key=api_key,
        )


    def stream_response(
        self, thread_id, message_id, run_id, assistant_id, model, stream_reasoning=True
    ):
        """
        Process conversation with dual streaming of content and reasoning.
        If a tool call trigger is detected, update run status to 'action_required',
        then wait for the status change and reprocess the original prompt.

        This function splits incoming tokens into reasoning and content segments
        (using <think> tags) while also handling a code mode. When a partial
        code-interpreter match is found, it enters code mode, processes and streams
        raw code via the _process_code_interpreter_chunks helper, and emits a start-of-code marker.

        Accumulated content is later used to finalize the conversation and validate
        tool responses.
        """
        # Start cancellation listener
        self.start_cancellation_listener(run_id)

        # Force correct model value via mapping (defaulting if not mapped)
        if self._get_model_map(value=model):
            model = self._get_model_map(value=model)
        else:
            model = "deepseek-ai/DeepSeek-V3"

        request_payload = {
            "model": model,
            "messages": self._set_up_context_window(
                assistant_id, thread_id, trunk=True
            ),
            "max_tokens": None,
            "temperature": 0.6,
            "stream": True,
        }

        assistant_reply = ""
        accumulated_content = ""
        reasoning_content = ""
        in_reasoning = False
        code_mode = False
        code_buffer = ""
        matched = False

        try:
            # Using self.client for streaming responses; adjust if deepseek_client is required.
            response = self.hyperbolic_client.chat.completions.create(**request_payload)

            for token in response:
                if self.check_cancellation_flag():
                    logging_utility.warning(f"Run {run_id} cancelled mid-stream")
                    yield json.dumps({"type": "error", "content": "Run cancelled"})
                    break

                if not hasattr(token, "choices") or not token.choices:
                    continue

                delta = token.choices[0].delta

                # Process any explicit reasoning content from delta.
                delta_reasoning = getattr(delta, "reasoning_content", "")
                if delta_reasoning:
                    reasoning_content += delta_reasoning
                    yield json.dumps({"type": "reasoning", "content": delta_reasoning})

                # Process content from delta.
                delta_content = getattr(delta, "content", "")
                if not delta_content:
                    continue

                # Optionally output raw content for debugging.
                sys.stdout.write(delta_content)
                sys.stdout.flush()

                # Split the content based on reasoning tags (<think> and </think>)
                segments = (
                    self.REASONING_PATTERN.split(delta_content)
                    if hasattr(self, "REASONING_PATTERN")
                    else [delta_content]
                )
                for seg in segments:
                    if not seg:
                        continue

                    # Check for reasoning start/end tags.
                    if seg == "<think>":
                        in_reasoning = True
                        reasoning_content += seg
                        logging_utility.debug("Yielding reasoning tag: %s", seg)
                        yield json.dumps({"type": "reasoning", "content": seg})
                        continue
                    elif seg == "</think>":
                        in_reasoning = False
                        reasoning_content += seg
                        logging_utility.debug("Yielding reasoning tag: %s", seg)
                        yield json.dumps({"type": "reasoning", "content": seg})
                        continue

                    if in_reasoning:
                        # If within reasoning, yield as reasoning content.
                        reasoning_content += seg
                        logging_utility.debug("Yielding reasoning segment: %s", seg)
                        yield json.dumps({"type": "reasoning", "content": seg})
                    else:
                        # Outside reasoning: process as normal content.
                        assistant_reply += seg
                        accumulated_content += seg
                        logging_utility.debug("Processing content segment: %s", seg)

                        # Check if a code-interpreter trigger is found (and not already in code mode).
                        partial_match = self.parse_code_interpreter_partial(
                            accumulated_content
                        )

                        if not code_mode:

                            if partial_match:
                                full_match = partial_match.get("full_match")
                                if full_match:
                                    match_index = accumulated_content.find(full_match)
                                    if match_index != -1:
                                        # Remove all content up to and including the trigger.
                                        accumulated_content = accumulated_content[
                                            match_index + len(full_match) :
                                        ]
                                code_mode = True
                                code_buffer = partial_match.get("code", "")

                                # Emit start-of-code block marker.
                                self.code_mode = True
                                yield json.dumps(
                                    {"type": "hot_code", "content": "```python\n"}
                                )
                                continue  # Skip further processing of this segment.

                        # If already in code mode, delegate to code-chunk processing.
                        if code_mode:

                            results, code_buffer = (
                                self._process_code_interpreter_chunks(seg, code_buffer)
                            )
                            for r in results:
                                yield r  # Yield raw code line(s).
                                assistant_reply += r  # Optionally accumulate the code.

                            continue

                        # Yield non-code content as normal.
                        if not code_buffer:
                            yield json.dumps({"type": "content", "content": seg}) + "\n"
                        else:
                            continue

                # Slight pause to allow incremental delivery.
                time.sleep(0.05)

        except Exception as e:
            error_msg = f"Hyperbolic SDK error: {str(e)}"
            logging_utility.error(error_msg, exc_info=True)
            combined = reasoning_content + assistant_reply
            self.handle_error(combined, thread_id, assistant_id, run_id)
            yield json.dumps({"type": "error", "content": error_msg})
            return

        # Finalize conversation if there's any assistant reply content.
        if assistant_reply:
            combined = reasoning_content + assistant_reply
            self.finalize_conversation(combined, thread_id, assistant_id, run_id)

        # -----------------------------------------
        #  Parsing the complete accumulated content
        #  for function calls.
        # -----------------------------------------
        if accumulated_content:
            self.parse_and_set_function_calls(accumulated_content, assistant_reply)

        self.run_service.update_run_status(run_id, validator.StatusEnum.completed)
        if reasoning_content:
            logging_utility.info("Final reasoning content: %s", reasoning_content)






    def process_function_calls(
        self,
        thread_id,
        run_id,
        assistant_id,
        model=None,
        api_key: Optional[str] = None,
    ):

        return super().process_function_calls(
            thread_id=thread_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            api_key=api_key,
        )

    def process_conversation(
        self,
        thread_id,
        message_id,
        run_id,
        assistant_id,
        model,
        stream_reasoning=False,
        api_key: Optional[str] = None,
    ):
        """
        Processes the conversation, passing the api_key down for use
        in the actual API request via override.
        """

        if self._get_model_map(value=model):
            model = self._get_model_map(value=model)

        logging_utility.info(
            f"Processing conversation for run {run_id} with model {model}. API key provided: {'Yes' if api_key else 'No'}"
        )

        # Stream the response, passing the api_key for override
        for chunk in self.stream_response(
            thread_id=thread_id,
            message_id=message_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            stream_reasoning=stream_reasoning,
            api_key=api_key,
        ):
            yield chunk

        # Process function calls, passing the api_key if needed by sub-calls
        for chunk in self.process_function_calls(
            thread_id=thread_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            api_key=api_key,  # <-- Keep Passing api_key
        ):
            yield chunk

        logging_utility.info(
            f"Finished processing conversation generator for run {run_id}"
        )
