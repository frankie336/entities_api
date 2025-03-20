import json
import os
import re
import sys
import time
from functools import lru_cache

from dotenv import load_dotenv
from together import Together  # Using the official Together SDK

from entities_api.inference.base_inference import BaseInference
from entities_api.services.logging_service import LoggingUtility

load_dotenv()
logging_utility = LoggingUtility()


class TogetherR1Inference(BaseInference):
    # Use <think> tags for reasoning content
    REASONING_PATTERN = re.compile(r'(<think>|</think>)')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = Together(api_key=os.getenv("TOGETHER_API_KEY"))
        # LRU-cache for assistant and message retrieval
        self._assistant_cache = lru_cache(maxsize=32)(self._cache_assistant_retrieval)
        self._message_cache = lru_cache(maxsize=64)(self._cache_message_retrieval)

    def setup_services(self):
        """Initialize TogetherAI SDK."""
        logging_utility.info("TogetherAI SDK initialized")

    def _cache_assistant_retrieval(self, assistant_id):
        """LRU-cached assistant retrieval."""
        logging_utility.debug(f"Cache miss for assistant {assistant_id}")
        return self.assistant_service.retrieve_assistant(assistant_id=assistant_id)

    def _cache_message_retrieval(self, thread_id, system_message):
        """LRU-cached message retrieval."""
        return self.message_service.get_formatted_messages(thread_id, system_message=system_message)

    def normalize_roles(self, conversation_history):
        """Reuse parent class normalization."""
        return super().normalize_roles(conversation_history)

    def _get_model_map(self, value):
        return super()._get_model_map(value)

    def _set_up_context_window(self, assistant_id, thread_id, trunk=True):
        return super()._set_up_context_window(assistant_id, thread_id, trunk=True)


    def stream_function_call_output(self, thread_id, run_id, assistant_id,
                                    model, stream_reasoning=False):
        return

    def stream_response(self, thread_id, message_id, run_id, assistant_id,
                             model, stream_reasoning=True):


        self.start_cancellation_listener(run_id)

        # Force correct model value
        if self._get_model_map(value=model):
            model = self._get_model_map(value=model)


        request_payload = {
            "model": model,
            "messages": self._set_up_context_window(assistant_id, thread_id, trunk=True) ,
            "max_tokens": None,
            "temperature": 0.6,
            "top_p": 0.95,
            "top_k": 50,
            "repetition_penalty": 1,
            "stop": ["<｜end▁of▁sentence｜>"],
            "stream": True
        }

        assistant_reply = ""
        reasoning_content = ""
        in_reasoning = False

        try:
            response = self.client.chat.completions.create(**request_payload)

            for token in response:
                if self.check_cancellation_flag():
                    logging_utility.warning(f"Run {run_id} cancelled mid-stream")
                    yield json.dumps({'type': 'error', 'content': 'Run cancelled'})
                    break

                if not hasattr(token, "choices") or not token.choices:
                    continue

                delta = token.choices[0].delta
                content = getattr(delta, "content", "")
                if not content:
                    continue

                # Optionally, print the raw content for debugging
                sys.stdout.write(content)
                sys.stdout.flush()

                # Split the content based on <think> tags
                segments = self.REASONING_PATTERN.split(content)
                for seg in segments:
                    if not seg:
                        continue
                    if seg == "<think>":
                        in_reasoning = True
                        reasoning_content += seg
                        logging_utility.debug("Yielding reasoning tag: %s", seg)
                        yield json.dumps({'type': 'reasoning', 'content': seg})
                    elif seg == "</think>":
                        in_reasoning = False
                        reasoning_content += seg
                        logging_utility.debug("Yielding reasoning tag: %s", seg)
                        yield json.dumps({'type': 'reasoning', 'content': seg})
                    else:
                        if in_reasoning:
                            reasoning_content += seg
                            logging_utility.debug("Yielding reasoning segment: %s", seg)
                            yield json.dumps({'type': 'reasoning', 'content': seg})
                        else:
                            assistant_reply += seg
                            logging_utility.debug("Yielding content segment: %s", seg)
                            yield json.dumps({'type': 'content', 'content': seg})
                # Optional: slight pause to allow incremental delivery
                time.sleep(0.01)

        except Exception as e:
            error_msg = f"Together SDK error: {str(e)}"
            logging_utility.error(error_msg, exc_info=True)
            combined = reasoning_content + assistant_reply
            self.handle_error(combined, thread_id, assistant_id, run_id)
            yield json.dumps({'type': 'error', 'content': error_msg})
            return

        # Finalize conversation if there's any assistant reply content
        if assistant_reply:
            combined = reasoning_content + assistant_reply
            self.finalize_conversation(combined, thread_id, assistant_id, run_id)

    def process_conversation(self, thread_id, message_id, run_id, assistant_id,
                             model, stream_reasoning=False):


        if self._get_model_map(value=model):
            model = self._get_model_map(value=model)

        # ---------------------------------------------
        # Stream the response and yield each chunk.
        # --------------------------------------------
        for chunk in self.stream_response(thread_id, message_id, run_id, assistant_id, model, stream_reasoning):
            yield chunk


    def __del__(self):
        """Cleanup resources."""
        super().__del__()
