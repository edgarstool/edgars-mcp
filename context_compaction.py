"""
Turn-Aware Context Compaction for Hermes Agent.

Provides a validation layer that prioritizes reasoning/thinking blocks during
context compaction. This ensures the agent's thinking process is preserved in
long-running sessions where the conversation history must be reduced to fit
within the model's context window.

Thinking blocks (Anthropic extended-thinking API) carry the model's internal
reasoning and must not be silently discarded when compacting turns.
"""

from __future__ import annotations

from typing import Any

# Content-block types that represent model reasoning.
THINKING_BLOCK_TYPES: frozenset[str] = frozenset({"thinking", "redacted_thinking"})


# ---------------------------------------------------------------------------
# Block / message inspection
# ---------------------------------------------------------------------------

def is_thinking_block(block: Any) -> bool:
    """Return True if *block* is a thinking or redacted-thinking content block."""
    return isinstance(block, dict) and block.get("type") in THINKING_BLOCK_TYPES


def message_has_thinking(message: Any) -> bool:
    """Return True if *message* contains at least one thinking block."""
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    if isinstance(content, list):
        return any(is_thinking_block(b) for b in content)
    return False


def extract_thinking_turn_indices(turns: list[dict]) -> list[int]:
    """Return a sorted list of indices of turns that contain thinking blocks."""
    return [i for i, turn in enumerate(turns) if message_has_thinking(turn)]


# ---------------------------------------------------------------------------
# Compaction
# ---------------------------------------------------------------------------

def compact_turns(turns: list[dict], max_turns: int) -> list[dict]:
    """Compact *turns* to at most *max_turns* while **preserving** thinking turns.

    When ``len(turns) <= max_turns`` the list is returned unchanged.

    Algorithm
    ---------
    1. Keep the *tail* of ``max_turns`` most-recent turns (the standard
       sliding-window approach).
    2. Any turn outside the tail that **contains a thinking block** is also
       kept, so reasoning context is never silently discarded.
    3. The returned list preserves the original chronological order.

    Parameters
    ----------
    turns:
        Ordered list of conversation turns (dicts with at least a ``role``
        and ``content`` field).
    max_turns:
        Maximum number of turns to keep from the tail.  Must be >= 1.

    Raises
    ------
    ValueError
        If *max_turns* is less than 1.
    """
    if max_turns < 1:
        raise ValueError("max_turns must be >= 1")
    if len(turns) <= max_turns:
        return list(turns)

    tail_start = len(turns) - max_turns
    kept: set[int] = set(range(tail_start, len(turns)))

    # Always include thinking turns that fall outside the tail window.
    for idx in extract_thinking_turn_indices(turns):
        if idx < tail_start:
            kept.add(idx)

    return [turns[i] for i in sorted(kept)]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class CompactionWarning:
    """Describes a single issue found during compaction validation."""

    def __init__(self, message: str) -> None:
        self.message = message

    def __repr__(self) -> str:  # pragma: no cover
        return f"CompactionWarning({self.message!r})"

    def __str__(self) -> str:
        return self.message

    def __eq__(self, other: object) -> bool:
        return isinstance(other, CompactionWarning) and self.message == other.message


def validate_compaction(
    original_turns: list[dict],
    compacted_turns: list[dict],
) -> list[CompactionWarning]:
    """Validate that *compacted_turns* has not silently dropped thinking blocks.

    Returns a (possibly empty) list of :class:`CompactionWarning` objects.
    An empty list means the compaction passed validation.

    Parameters
    ----------
    original_turns:
        The full, uncompacted conversation history.
    compacted_turns:
        The result of compaction to be validated.
    """
    warnings: list[CompactionWarning] = []

    original_count = sum(1 for t in original_turns if message_has_thinking(t))
    compacted_count = sum(1 for t in compacted_turns if message_has_thinking(t))

    if compacted_count < original_count:
        dropped = original_count - compacted_count
        warnings.append(
            CompactionWarning(
                f"Context compaction dropped {dropped} thinking turn(s); "
                f"original had {original_count}, compacted has {compacted_count}. "
                "Use compact_turns() to preserve reasoning blocks."
            )
        )

    return warnings
