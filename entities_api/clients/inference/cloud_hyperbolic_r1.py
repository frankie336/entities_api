import json
import re

from entities_api.clients.client_message_client import ClientMessageService
from entities_api.clients.inference.hyperbolic_base import HyperbolicBaseInference
from entities_api.services.logging_service import LoggingUtility

# Initialize logging utility
logging_utility = LoggingUtility()

class HyperbolicR1Inference(HyperbolicBaseInference):
    DEFAULT_MODEL = "deepseek-ai/DeepSeek-R1"
    DEFAULT_TEMPERATURE = 0.6
    # Regex to capture the reasoning markers: <think> and </think>
    REASONING_PATTERN = re.compile(r'(<think>|</think>)')

    def __init__(self):
        super().__init__()
        # State to persist across streamed chunks
        self.token_state = {
            "in_reasoning": False,
            "assistant_reply": "",
            "reasoning_content": ""
        }

    def _process_stream(self, response, run_id):
        """
        Override the base class stream processing to yield multiple tokens per line.
        Iterates over each line from the streaming response and, for each line,
        iterates over all tokens produced by process_line.
        """
        for line in response.iter_lines(decode_unicode=True):
            if self._check_cancellation(run_id):
                break

            # process_line returns a generator of tokens for this line.
            for token in self.process_line(line):
                if token:
                    yield token
                    # Optionally, introduce a slight pause:
                    # time.sleep(0.005)

    def process_line(self, line):
        """
        Process a single streamed line from the API response.
        Returns a generator of JSON-encoded tokens (content or reasoning segments).
        """
        if not line or line == "[DONE]":
            return
        # Remove the "data:" prefix if present.
        if line.startswith("data:"):
            line = line[len("data:"):].strip()

        try:
            chunk = json.loads(line)
        except json.JSONDecodeError:
            logging_utility.error("Failed to decode JSON from chunk: %s", line)
            return

        choices = chunk.get("choices", [])
        if not choices:
            return

        delta = choices[0].get("delta", {})
        content_chunk = delta.get("content", "")
        if content_chunk:
            # Delegate the token segmentation to a dedicated method.
            yield from self._process_content_chunk(content_chunk)

    def _process_content_chunk(self, content_chunk):
        """
        Dedicated method to process a content chunk using <think> and </think> markers.
        Splits the chunk into tokens, toggles the state accordingly, accumulates content,
        and yields JSON messages for each token.
        """
        tokens = re.split(self.REASONING_PATTERN, content_chunk)
        for token in tokens:
            if token == '<think>':
                self.token_state["in_reasoning"] = True
            elif token == '</think>':
                self.token_state["in_reasoning"] = False
            elif token:
                if self.token_state["in_reasoning"]:
                    self.token_state["reasoning_content"] += token
                    logging_utility.info("Yielding reasoning segment: %s", token)
                    yield json.dumps({'type': 'reasoning', 'content': token})
                else:
                    self.token_state["assistant_reply"] += token
                    logging_utility.info("Yielding content segment: %s", token)
                    yield json.dumps({'type': 'content', 'content': token})

    def _finalize_run(self, run_id, assistant_id, thread_id, role, content, sender_id):
        """
        Override finalization to combine the raw reasoning text and the message content,
        ensuring that all raw reasoning appears first followed by the message text.
        The combined body is then saved as one message chunk.
        """
        # Concatenate reasoning text first, then the assistant message.
        final_text = self.token_state["reasoning_content"] + self.token_state["assistant_reply"]

        message_service = ClientMessageService()
        message_service.save_assistant_message_chunk(
            role='assistant',
            thread_id=thread_id,
            content=final_text,
            assistant_id=assistant_id,
            sender_id=assistant_id,
            is_last_chunk=True
        )
        logging_utility.info("Final combined content stored successfully: %s", final_text)

        # Delegate common finalization tasks (e.g., run status update) to the base class.
        super()._finalize_run(run_id, assistant_id, thread_id, role, content, sender_id)
