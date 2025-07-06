from __future__ import annotations

import os
from typing import List

from projectdavid_common.utilities.logging_service import LoggingUtility
from transformers import AutoTokenizer
from transformers.utils import logging as hf_logging

LOG = LoggingUtility()
hf_logging.set_verbosity_error()


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
        """
        Try to load `model_name`; fall back to a public model if that fails.
        """
        try:
            return AutoTokenizer.from_pretrained(model_name)
        except Exception as exc:
            LOG.warning(
                "Tokenizer %s unavailable (%s) – falling back to %s",
                model_name,
                exc.__class__.__name__,
                cls.FALLBACK_MODEL,
            )
            return AutoTokenizer.from_pretrained(cls.FALLBACK_MODEL)

    def count_tokens(self, text: str) -> int:
        """Return #tokens for `text` (special tokens excluded)."""
        return len(self.tokenizer.encode(text or "", add_special_tokens=False))

    def truncate(self, conversation: List[dict]) -> List[dict]:
        """
        Trim conversation and merge consecutive same-role messages.
        """
        system_msgs = [m for m in conversation if m.get("role") == "system"]
        other_msgs = [m for m in conversation if m.get("role") != "system"]
        sys_tokens = sum((self.count_tokens(m["content"]) for m in system_msgs))
        oth_tokens = sum((self.count_tokens(m["content"]) for m in other_msgs))
        total_tokens = sys_tokens + oth_tokens
        threshold_tokens = self.max_context_window * self.threshold_percentage
        if total_tokens <= threshold_tokens:
            return self.merge_consecutive_messages(conversation)
        budget = threshold_tokens - sys_tokens
        truncated = other_msgs.copy()
        while truncated and oth_tokens > budget:
            removed = truncated.pop(0)
            oth_tokens -= self.count_tokens(removed["content"])
        combined = system_msgs + truncated
        combined.sort(key=lambda m: conversation.index(m))
        return self.merge_consecutive_messages(combined)

    @staticmethod
    def merge_consecutive_messages(conversation: List[dict]) -> List[dict]:
        """
        Merge consecutive messages from the same role.
        """
        if not conversation:
            return conversation
        merged = [conversation[0]]
        for msg in conversation[1:]:
            if msg["role"] == merged[-1]["role"]:
                merged[-1]["content"] += "\n" + msg["content"]
            else:
                merged.append(msg)
        return merged
