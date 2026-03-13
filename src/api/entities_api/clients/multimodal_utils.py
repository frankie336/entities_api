# src/api/entities_api/clients/multimodal_utils.py
"""
Shared multimodal utilities for OpenAI-compatible providers.

Used by:
    - vllm_raw_stream.py   (vLLM /v1/chat/completions path)
    - qwen_base.py         (TogetherAI, Hyperbolic, etc.)

NOT used by:
    - ollama_client.py     (Ollama has its own format: images as a sibling
                            key with raw base64 — see _normalise_for_ollama)

The functions here produce the standard OpenAI multimodal message format:
    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}

This is the format accepted by vLLM, TogetherAI, Hyperbolic, and any other
provider that follows the OpenAI vision spec.
"""

from __future__ import annotations

from typing import Any, Dict, List

from projectdavid_common.utilities.logging_service import LoggingUtility

LOG = LoggingUtility()


def is_multimodal(messages: List[Dict]) -> bool:
    """
    Return True if any message carries list content (hydrated image blocks).

    Plain-text messages always have str content.  After hydration, messages
    with image attachments have list content containing typed blocks.
    """
    return any(isinstance(m.get("content"), list) for m in messages)


def normalise_for_chat(messages: List[Dict]) -> List[Dict]:
    """
    Convert hydrated messages into the OpenAI multimodal chat format.

    Accepts the internal hydrated format produced by NativeExecutionService
    .hydrate_messages() and converts it to the OpenAI vision spec that vLLM,
    TogetherAI, Hyperbolic, and compatible providers accept.

    Hydrated input:
        {"role": "user", "content": [
            {"type": "text",  "text":  "What is in this image?"},
            {"type": "image", "image": "data:image/jpeg;base64,/9j/..."},
        ]}

    OpenAI output:
        {"role": "user", "content": [
            {"type": "text",     "text": "What is in this image?"},
            {"type": "image_url","image_url": {"url": "data:image/jpeg;base64,/9j/..."}},
        ]}

    Plain text messages (str content) pass through untouched.
    Already-normalised image_url blocks also pass through unchanged.
    """
    normalised = []

    for m in messages:
        content = m.get("content")

        if not isinstance(content, list):
            # Plain text — pass straight through
            normalised.append(m)
            continue

        converted_blocks = []

        for block in content:
            if not isinstance(block, dict):
                continue

            btype = block.get("type")

            if btype == "text":
                converted_blocks.append({"type": "text", "text": block.get("text", "")})

            elif btype == "image":
                # Internal hydrated format → OpenAI image_url format
                data_uri = block.get("image", "")
                converted_blocks.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": data_uri},
                    }
                )

            elif btype == "image_url":
                # Already in OpenAI format — pass through unchanged
                converted_blocks.append(block)

            else:
                LOG.warning("normalise_for_chat: unknown block type '%s', skipping.", btype)

        normalised.append({**m, "content": converted_blocks})

    return normalised
