# streaming/semantic_accumulator.py

from __future__ import annotations
from typing import List, Optional, Iterable, Any


class SemanticAccumulator:
    """
    SemanticAccumulator is the single source of truth for a streamed run.

    Invariants:
    - Preserves exact semantic order of all deltas
    - Does NOT trust provider-level completion flags
    - Can reconstruct the full conversation deterministically
    - Supports reasoning suppression without losing ordering
    """

    def __init__(self, *, stream_reasoning: bool):
        self.stream_reasoning = stream_reasoning

        # Ordered ground truth (never lossy)
        self._sequence: List[Any] = []

        # Convenience buffers (derived, not authoritative)
        self._text_buffer: List[str] = []
        self._reasoning_buffer: List[str] = []
        self._tool_fragments: List[str] = []

        # Semantic state
        self._current_block: Optional[str] = None  # text | reasoning | tool
        self._tool_open: bool = False

    # ------------------------------------------------------------------
    # INGESTION
    # ------------------------------------------------------------------

    def ingest(self, delta: Any) -> None:
        """
        Ingest a provider-normalized delta.

        Delta contract (already enforced upstream):
            delta.kind in {"text", "reasoning", "tool"}
            delta.payload
            delta.tool_complete (optional, advisory only)
        """

        # Always preserve ordering
        self._sequence.append(delta)

        if delta.kind == "text":
            self._enter_block("text")
            self._text_buffer.append(delta.payload)

        elif delta.kind == "reasoning":
            self._enter_block("reasoning")
            self._reasoning_buffer.append(delta.payload)

        elif delta.kind == "tool":
            self._enter_block("tool")
            self._tool_open = True
            self._tool_fragments.append(delta.payload)

        else:
            raise ValueError(f"Unknown delta kind: {delta.kind}")

    # ------------------------------------------------------------------
    # SEMANTIC STATE
    # ------------------------------------------------------------------

    def _enter_block(self, block: str) -> None:
        if self._current_block == block:
            return

        # Close tool block if transitioning away
        if self._current_block == "tool" and block != "tool":
            self._tool_open = False

        self._current_block = block

    # ------------------------------------------------------------------
    # EMISSION DECISIONS (NO YIELDS)
    # ------------------------------------------------------------------

    def should_emit_text(self, delta: Any) -> bool:
        return delta.kind == "text"

    def should_emit_reasoning(self, delta: Any) -> bool:
        return self.stream_reasoning and delta.kind == "reasoning"

    # ------------------------------------------------------------------
    # TOOL DETECTION
    # ------------------------------------------------------------------

    def tool_call_detected(self) -> bool:
        """
        Tool calls are detected semantically, not via provider flags.
        """
        return self._tool_open or bool(self._tool_fragments)

    def finalize_tool_call(self) -> str:
        """
        Deterministically assemble the raw tool payload.
        Parsing and validation are delegated upstream.
        """
        if not self._tool_fragments:
            raise RuntimeError("finalize_tool_call called with no tool fragments")

        return self._assemble_tool_payload(self._tool_fragments)

    # ------------------------------------------------------------------
    # RECONSTRUCTION / DEBUG
    # ------------------------------------------------------------------

    def ordered_deltas(self) -> Iterable[Any]:
        """
        Canonical replay of the stream.
        """
        return iter(self._sequence)

    def full_text(self) -> str:
        return "".join(self._text_buffer)

    def full_reasoning(self) -> str:
        return "".join(self._reasoning_buffer)

    # ------------------------------------------------------------------
    # INTERNAL
    # ------------------------------------------------------------------

    def _assemble_tool_payload(self, fragments: List[str]) -> str:
        """
        Tool assembly is intentionally dumb and deterministic.
        No parsing. No validation. No assumptions.
        """
        return "".join(fragments)
