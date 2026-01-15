from typing import Any, Generator

from .base_provider import BaseHyperbolicProvider


# --------------------------------------------------------------------------- #
# 1. DeepSeek Specialization (V3 / R1)
# --------------------------------------------------------------------------- #
class HyperbolicDs1(BaseHyperbolicProvider):
    """DeepSeek specialized refiner to handle <fc> tags server-side."""

    def _get_refined_generator(self, raw_stream: Any, run_id: str) -> Generator[dict, None, None]:
        tag_start, tag_end = "<fc>", "</fc>"
        buffer, is_in_fc = "", False

        for token in raw_stream:
            if not token.choices or not token.choices[0].delta: continue
            seg = getattr(token.choices[0].delta, "content", "")
            if not seg: continue

            for char in seg:
                buffer += char
                if not is_in_fc:
                    if tag_start.startswith(buffer):
                        if buffer == tag_start:
                            is_in_fc, buffer = True, ""
                        continue
                    yield {"type": "content", "content": buffer, "run_id": run_id}
                    buffer = ""
                else:
                    if tag_end in buffer:
                        parts = buffer.split(tag_end, 1)
                        if parts[0]:
                            yield {"type": "call_arguments", "content": parts[0], "run_id": run_id}
                        is_in_fc, buffer = False, parts[1] if len(parts) > 1 else ""
                    elif any(tag_end.startswith(buffer[i:]) for i in range(len(buffer))):
                        continue
                    else:
                        yield {"type": "call_arguments", "content": buffer, "run_id": run_id}
                        buffer = ""


# --------------------------------------------------------------------------- #
# 2. Llama 3.3 Specialization
# --------------------------------------------------------------------------- #
class HyperbolicLlama33(BaseHyperbolicProvider):
    """Meta-Llama 3.3 specialization. Uses standard generator logic."""
    # We don't override _get_refined_generator because the Base version
    # handles standard content flow perfectly.
    pass


# --------------------------------------------------------------------------- #
# 3. Qwen Qwq Specialization (Reasoning Interception)
# --------------------------------------------------------------------------- #
class HyperbolicQuenQwq32B(BaseHyperbolicProvider):
    """Qwen specialization with <think> tag interception for reasoning."""

    def _get_refined_generator(self, raw_stream: Any, run_id: str) -> Generator[dict, None, None]:
        in_reasoning = False

        for token in raw_stream:
            if not token.choices or not token.choices[0].delta: continue
            seg = getattr(token.choices[0].delta, "content", "")
            if not seg: continue

            # Handle Reasoning Blocks
            if "<think>" in seg:
                in_reasoning = True
                yield {"type": "reasoning", "content": "<think>", "run_id": run_id}
                seg = seg.replace("<think>", "")

            if "</think>" in seg:
                in_reasoning = False
                yield {"type": "reasoning", "content": "</think>", "run_id": run_id}
                seg = seg.replace("</think>", "")

            if in_reasoning:
                yield {"type": "reasoning", "content": seg, "run_id": run_id}
            else:
                yield {"type": "content", "content": seg, "run_id": run_id}
