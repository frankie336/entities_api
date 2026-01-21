import copy
import json
import logging
from typing import Any, AsyncGenerator, Generator

# Configure logger
logger = logging.getLogger("HyperbolicShunt")


class HyperbolicReasoningShunt:
    """
    Normalizes Hyperbolic streams.
    If the model uses Hermes 3 style tags (<|channel|>analysis...),
    it shifts that text from 'content' to 'reasoning_content'.
    """

    # Hermes 3 / GPT-OSS-120b specific tags
    TAG_REASONING_START = "<|channel|>analysis<|message|>"
    TAG_CONTENT_START = "<|channel|>final<|message|>"
    TAG_TURN_SWITCH = "<|end|><|start|>assistant"  # Transition garbage

    def __init__(self):
        self.buffer = ""
        self.state = "unknown"  # states: unknown, reasoning, content
        self.max_tag_len = max(
            len(self.TAG_REASONING_START),
            len(self.TAG_CONTENT_START),
            len(self.TAG_TURN_SWITCH),
        )

        # Flags to prevent log spam per stream
        self._logged_native_detection = False
        self._logged_shunt_activation = False

    def process_stream(self, iterator):
        """
        Accepts an iterator of OpenAI-compatible chunks (dicts or objects).
        Yields normalized chunks.
        """
        for chunk in iterator:
            # 1. Identify valid data
            if not chunk:
                continue

            # Handle object vs dict access
            is_dict = isinstance(chunk, dict)
            choices = chunk.get("choices", []) if is_dict else chunk.choices

            if not choices:
                yield chunk
                continue

            delta = choices[0].get("delta", {}) if is_dict else choices[0].delta

            # 2. CHECK FOR NATIVE REASONING (The 20b Case)
            # If the API is already populating reasoning_content, just pass it through.
            native_reasoning = (
                delta.get("reasoning_content")
                if is_dict
                else getattr(delta, "reasoning_content", None)
            )

            if native_reasoning:
                if not self._logged_native_detection:
                    logger.info(
                        "✅ [Native] Provider is sending 'reasoning_content' natively. Shunt is passing through."
                    )
                    self._logged_native_detection = True

                # If we see native reasoning, we assume this model doesn't need tag parsing.
                # Clear buffer just in case, reset state, and yield.
                if self.buffer:
                    yield self._create_chunk(chunk, self.buffer, None, is_dict)
                    self.buffer = ""
                yield chunk
                continue

            # 3. HANDLE TAGGED CONTENT (The 120b Case)
            raw_content = (
                delta.get("content", "") if is_dict else getattr(delta, "content", "")
            )

            # If no content and no native reasoning, it's a keep-alive or empty chunk
            if not raw_content:
                yield chunk
                continue

            # Append to buffer and parse
            self.buffer += raw_content

            # Iterate to extract valid text parts from the buffer
            while True:
                # A. Clean Transition Garbage
                if self.TAG_TURN_SWITCH in self.buffer:
                    logger.debug("🧹 [Shunt] Scrubbed transition garbage tag.")
                    self.buffer = self.buffer.replace(self.TAG_TURN_SWITCH, "")

                # B. Check for REASONING START
                if self.TAG_REASONING_START in self.buffer:
                    logger.info(
                        "🔵 [Shunt] Detected <|channel|>analysis. Switching to REASONING mode."
                    )
                    pre, post = self.buffer.split(self.TAG_REASONING_START, 1)
                    if pre:
                        yield self._create_chunk(
                            chunk, pre, None, is_dict
                        )  # Flush pre-tag text
                    self.state = "reasoning"
                    self.buffer = post
                    continue

                # C. Check for CONTENT START
                if self.TAG_CONTENT_START in self.buffer:
                    logger.info(
                        "🟢 [Shunt] Detected <|channel|>final. Switching to CONTENT mode."
                    )
                    pre, post = self.buffer.split(self.TAG_CONTENT_START, 1)
                    if pre:
                        # Anything before this tag was reasoning
                        yield self._create_chunk(chunk, "", pre, is_dict)
                    self.state = "content"
                    self.buffer = post
                    continue

                # D. Safety Window (Wait if we have a partial tag)
                potential_match = False
                for tag in [
                    self.TAG_REASONING_START,
                    self.TAG_CONTENT_START,
                    self.TAG_TURN_SWITCH,
                ]:
                    for i in range(1, len(tag)):
                        if self.buffer.endswith(tag[:i]):
                            potential_match = True
                            break
                    if potential_match:
                        break

                if potential_match:
                    # Don't yield yet, wait for next chunk
                    break
                else:
                    # No potential tag, yield everything
                    if self.buffer:
                        text_to_yield = self.buffer
                        self.buffer = ""

                        # LOGIC SWITCH:
                        if self.state == "reasoning":
                            if not self._logged_shunt_activation:
                                logger.info(
                                    "⚡ [Shunt] Active. Moving content -> reasoning_content."
                                )
                                self._logged_shunt_activation = True

                            # Yield empty content, populated reasoning
                            yield self._create_chunk(chunk, "", text_to_yield, is_dict)
                        else:
                            # State is 'unknown' or 'content' -> standard content
                            yield self._create_chunk(
                                chunk, text_to_yield, None, is_dict
                            )
                    break

        # 4. Flush remaining buffer at end of stream
        if self.buffer:
            text = self.buffer.replace(self.TAG_TURN_SWITCH, "")
            if text:
                if self.state == "reasoning":
                    yield self._create_chunk(chunk, "", text, is_dict)
                else:
                    yield self._create_chunk(chunk, text, None, is_dict)

    def _create_chunk(self, original_chunk, content_text, reasoning_text, is_dict):
        """Helper to reconstruct the chunk with shifted data"""
        new_chunk = copy.deepcopy(original_chunk)

        if is_dict:
            new_chunk["choices"][0]["delta"]["content"] = content_text
            new_chunk["choices"][0]["delta"]["reasoning_content"] = reasoning_text
        else:
            # Assuming Pydantic model or SimpleNamespace
            new_chunk.choices[0].delta.content = content_text
            try:
                new_chunk.choices[0].delta.reasoning_content = reasoning_text
            except AttributeError:
                # If the object is strict, we might have to rely on content only
                # Often happens if the SDK model definition doesn't have the field yet
                logger.warning(
                    "⚠️ [Shunt] Could not set reasoning_content on chunk object (AttributeError)."
                )
                pass

        return new_chunk


# --- USAGE EXAMPLE ---

# 1. Initialize the Shunt

shunt = HyperbolicReasoningShunt()

# 2. Wrap your API response iterator
# response = client.chat.completions.create(..., stream=True)
# normalized_stream = shunt.process_stream(response)

# 3. Consume normally
# for chunk in normalized_stream:
#     delta = chunk.choices[0].delta
#     if delta.reasoning_content:
#         print(f"thinking: {delta.reasoning_content}")
#     if delta.content:
#         print(f"content: {delta.content}")
