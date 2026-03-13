# src/api/entities_api/services/conversation_truncator.py
from __future__ import annotations

import os
from functools import lru_cache
from typing import List

from projectdavid_common import LoggingUtility
from transformers import AutoTokenizer
from transformers.utils import logging as hf_logging

LOG = LoggingUtility()
hf_logging.set_verbosity_error()


@lru_cache(maxsize=8)
def _load_tokenizer(model_name: str):
    """Load and cache tokenizer — one load per model name per process."""
    return AutoTokenizer.from_pretrained(model_name)


class ConversationTruncator:
    """
    Utility to trim a conversation to <= `threshold_percentage`
    of `max_context_window` tokens (system messages are never dropped).
    Consecutive messages from the same role are merged.
    """

    FALLBACK_MODEL = os.getenv("TRUNCATOR_MODEL", "gpt2")

    def __init__(
        self, model_name: str, max_context_window: int, threshold_percentage: float
    ) -> None:
        self.max_context_window = max_context_window
        self.threshold_percentage = threshold_percentage
        self.tokenizer = self._safe_load_tokenizer(model_name)

    @classmethod
    def _safe_load_tokenizer(cls, model_name: str):
        try:
            return _load_tokenizer(model_name)
        except Exception as exc:
            LOG.warning(
                "Tokenizer %s unavailable (%s) — falling back to %s",
                model_name,
                exc.__class__.__name__,
                cls.FALLBACK_MODEL,
            )
            return _load_tokenizer(cls.FALLBACK_MODEL)

    def _count_tokens_batch(self, texts: List[str]) -> List[int]:
        """
        Tokenize a list of strings in one batched call — far cheaper than
        calling encode() once per message in a loop.
        """
        if not texts:
            return []
        encoded = self.tokenizer(
            texts,
            add_special_tokens=False,
            return_attention_mask=False,
            return_length=True,  # returns lengths directly
        )
        # `return_length=True` gives us encoded["length"] as a list of ints
        return encoded["length"]

    def count_tokens(self, text: str) -> int:
        """Return token count for a single string (special tokens excluded)."""
        return len(self.tokenizer.encode(text or "", add_special_tokens=False))

    def truncate(self, conversation: List[dict]) -> List[dict]:
        """
        Trim conversation and merge consecutive same-role messages.
        """
        system_msgs = [m for m in conversation if m.get("role") == "system"]
        other_msgs = [m for m in conversation if m.get("role") != "system"]

        # Single batched tokenizer call for all messages
        all_texts = [m["content"] for m in system_msgs + other_msgs]
        all_counts = self._count_tokens_batch(all_texts)

        sys_tokens = sum(all_counts[: len(system_msgs)])
        msg_counts = list(zip(other_msgs, all_counts[len(system_msgs) :]))
        oth_tokens = sum(c for _, c in msg_counts)

        threshold_tokens = self.max_context_window * self.threshold_percentage

        if sys_tokens + oth_tokens <= threshold_tokens:
            return self.merge_consecutive_messages(conversation)

        budget = threshold_tokens - sys_tokens
        while msg_counts and oth_tokens > budget:
            _, cost = msg_counts.pop(0)
            oth_tokens -= cost

        kept_others = [m for m, _ in msg_counts]

        # O(n) restore original order using a pre-built index
        original_index = {id(m): i for i, m in enumerate(conversation)}
        combined = sorted(system_msgs + kept_others, key=lambda m: original_index[id(m)])

        return self.merge_consecutive_messages(combined)

    @staticmethod
    def merge_consecutive_messages(conversation: List[dict]) -> List[dict]:
        if not conversation:
            return conversation
        merged = [conversation[0]]
        for msg in conversation[1:]:
            if msg["role"] == merged[-1]["role"]:
                merged[-1]["content"] += "\n" + msg["content"]
            else:
                merged.append(msg)
        return merged
