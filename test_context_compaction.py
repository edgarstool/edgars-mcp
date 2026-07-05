"""Unit tests for the context_compaction module."""

import unittest

import context_compaction as cc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _text_turn(role: str, text: str) -> dict:
    """Build a plain-text conversation turn."""
    return {"role": role, "content": [{"type": "text", "text": text}]}


def _thinking_turn(role: str, thinking: str, text: str) -> dict:
    """Build a turn that contains a thinking block followed by a text block."""
    return {
        "role": role,
        "content": [
            {"type": "thinking", "thinking": thinking},
            {"type": "text", "text": text},
        ],
    }


def _redacted_thinking_turn(role: str, data: str = "opaque") -> dict:
    """Build a turn containing a redacted_thinking block."""
    return {
        "role": role,
        "content": [
            {"type": "redacted_thinking", "data": data},
            {"type": "text", "text": "answer"},
        ],
    }


# ---------------------------------------------------------------------------
# is_thinking_block
# ---------------------------------------------------------------------------

class IsThinkingBlockTests(unittest.TestCase):
    def test_thinking_type_returns_true(self):
        self.assertTrue(cc.is_thinking_block({"type": "thinking", "thinking": "..."}))

    def test_redacted_thinking_returns_true(self):
        self.assertTrue(cc.is_thinking_block({"type": "redacted_thinking", "data": "x"}))

    def test_text_type_returns_false(self):
        self.assertFalse(cc.is_thinking_block({"type": "text", "text": "hello"}))

    def test_tool_use_returns_false(self):
        self.assertFalse(cc.is_thinking_block({"type": "tool_use", "name": "echo"}))

    def test_non_dict_returns_false(self):
        self.assertFalse(cc.is_thinking_block("thinking"))
        self.assertFalse(cc.is_thinking_block(None))
        self.assertFalse(cc.is_thinking_block(42))

    def test_missing_type_key_returns_false(self):
        self.assertFalse(cc.is_thinking_block({"thinking": "no type key"}))


# ---------------------------------------------------------------------------
# message_has_thinking
# ---------------------------------------------------------------------------

class MessageHasThinkingTests(unittest.TestCase):
    def test_message_with_thinking_block(self):
        msg = _thinking_turn("assistant", "reasoning", "result")
        self.assertTrue(cc.message_has_thinking(msg))

    def test_message_with_redacted_thinking(self):
        msg = _redacted_thinking_turn("assistant")
        self.assertTrue(cc.message_has_thinking(msg))

    def test_plain_text_message(self):
        msg = _text_turn("user", "hello")
        self.assertFalse(cc.message_has_thinking(msg))

    def test_string_content_returns_false(self):
        self.assertFalse(cc.message_has_thinking({"role": "user", "content": "hi"}))

    def test_non_dict_returns_false(self):
        self.assertFalse(cc.message_has_thinking("not a dict"))
        self.assertFalse(cc.message_has_thinking(None))

    def test_empty_content_list(self):
        self.assertFalse(cc.message_has_thinking({"role": "assistant", "content": []}))


# ---------------------------------------------------------------------------
# extract_thinking_turn_indices
# ---------------------------------------------------------------------------

class ExtractThinkingTurnIndicesTests(unittest.TestCase):
    def test_returns_correct_indices(self):
        turns = [
            _text_turn("user", "q1"),
            _thinking_turn("assistant", "r1", "a1"),
            _text_turn("user", "q2"),
            _thinking_turn("assistant", "r2", "a2"),
            _text_turn("user", "q3"),
        ]
        self.assertEqual([1, 3], cc.extract_thinking_turn_indices(turns))

    def test_no_thinking_turns_returns_empty(self):
        turns = [_text_turn("user", "q"), _text_turn("assistant", "a")]
        self.assertEqual([], cc.extract_thinking_turn_indices(turns))

    def test_empty_list_returns_empty(self):
        self.assertEqual([], cc.extract_thinking_turn_indices([]))


# ---------------------------------------------------------------------------
# compact_turns
# ---------------------------------------------------------------------------

class CompactTurnsTests(unittest.TestCase):
    def test_no_compaction_needed_when_under_limit(self):
        turns = [_text_turn("user", str(i)) for i in range(5)]
        result = cc.compact_turns(turns, max_turns=10)
        self.assertEqual(turns, result)

    def test_no_compaction_needed_when_equal_to_limit(self):
        turns = [_text_turn("user", str(i)) for i in range(5)]
        result = cc.compact_turns(turns, max_turns=5)
        self.assertEqual(turns, result)

    def test_tail_window_kept_when_no_thinking(self):
        turns = [_text_turn("user", str(i)) for i in range(10)]
        result = cc.compact_turns(turns, max_turns=4)
        self.assertEqual(turns[-4:], result)

    def test_thinking_turns_outside_tail_are_preserved(self):
        turns = [
            _thinking_turn("assistant", "r0", "a0"),  # index 0 — thinking
            _text_turn("user", "q1"),
            _text_turn("assistant", "a1"),
            _text_turn("user", "q2"),
            _text_turn("assistant", "a2"),
        ]
        # max_turns=2 → tail is indices [3, 4]; index 0 has thinking → kept
        result = cc.compact_turns(turns, max_turns=2)
        self.assertIn(turns[0], result)
        self.assertIn(turns[3], result)
        self.assertIn(turns[4], result)
        self.assertEqual(3, len(result))

    def test_thinking_turns_inside_tail_are_preserved(self):
        turns = [
            _text_turn("user", "q0"),
            _text_turn("assistant", "a0"),
            _text_turn("user", "q1"),
            _thinking_turn("assistant", "r2", "a2"),  # inside tail window
        ]
        result = cc.compact_turns(turns, max_turns=3)
        self.assertIn(turns[3], result)

    def test_order_preserved_after_compaction(self):
        turns = [
            _thinking_turn("assistant", "r0", "a0"),  # index 0
            _text_turn("user", "q1"),
            _text_turn("assistant", "a1"),
            _text_turn("user", "q2"),
            _text_turn("assistant", "a2"),
        ]
        result = cc.compact_turns(turns, max_turns=2)
        roles = [t["role"] for t in result]
        # Order must match original order
        self.assertEqual(["assistant", "user", "assistant"], roles)

    def test_max_turns_one_preserves_thinking_beyond_tail(self):
        turns = [
            _thinking_turn("assistant", "r", "a"),
            _text_turn("user", "q"),
            _text_turn("assistant", "a"),
        ]
        result = cc.compact_turns(turns, max_turns=1)
        # tail = [2], but index 0 has thinking so it must be included
        self.assertIn(turns[0], result)
        self.assertIn(turns[2], result)

    def test_invalid_max_turns_raises_value_error(self):
        with self.assertRaises(ValueError):
            cc.compact_turns([], max_turns=0)

    def test_invalid_max_turns_negative_raises_value_error(self):
        with self.assertRaises(ValueError):
            cc.compact_turns([], max_turns=-5)

    def test_returns_new_list_not_same_object(self):
        turns = [_text_turn("user", "q")]
        result = cc.compact_turns(turns, max_turns=1)
        self.assertIsNot(turns, result)


# ---------------------------------------------------------------------------
# validate_compaction
# ---------------------------------------------------------------------------

class ValidateCompactionTests(unittest.TestCase):
    def test_no_warnings_when_thinking_preserved(self):
        original = [
            _thinking_turn("assistant", "r", "a"),
            _text_turn("user", "q"),
        ]
        compacted = list(original)
        warnings = cc.validate_compaction(original, compacted)
        self.assertEqual([], warnings)

    def test_warning_when_thinking_turn_dropped(self):
        original = [
            _thinking_turn("assistant", "r", "a"),
            _text_turn("user", "q"),
        ]
        compacted = [_text_turn("user", "q")]
        warnings = cc.validate_compaction(original, compacted)
        self.assertEqual(1, len(warnings))
        self.assertIn("1 thinking turn", str(warnings[0]))

    def test_warning_counts_multiple_dropped_turns(self):
        original = [
            _thinking_turn("assistant", "r1", "a1"),
            _thinking_turn("assistant", "r2", "a2"),
            _text_turn("user", "q"),
        ]
        compacted = [_text_turn("user", "q")]
        warnings = cc.validate_compaction(original, compacted)
        self.assertEqual(1, len(warnings))
        self.assertIn("2 thinking turn", str(warnings[0]))

    def test_no_thinking_in_either_produces_no_warnings(self):
        original = [_text_turn("user", "q"), _text_turn("assistant", "a")]
        compacted = [_text_turn("user", "q")]
        self.assertEqual([], cc.validate_compaction(original, compacted))

    def test_empty_lists_produce_no_warnings(self):
        self.assertEqual([], cc.validate_compaction([], []))

    def test_compaction_warning_str_is_human_readable(self):
        w = cc.CompactionWarning("some problem")
        self.assertEqual("some problem", str(w))

    def test_compaction_warning_equality(self):
        self.assertEqual(cc.CompactionWarning("x"), cc.CompactionWarning("x"))
        self.assertNotEqual(cc.CompactionWarning("x"), cc.CompactionWarning("y"))


# ---------------------------------------------------------------------------
# Integration: compact_turns + validate_compaction round-trip
# ---------------------------------------------------------------------------

class RoundTripTests(unittest.TestCase):
    def test_compact_then_validate_produces_no_warnings(self):
        original = [
            _thinking_turn("assistant", "r0", "a0"),
            _text_turn("user", "q1"),
            _text_turn("assistant", "a1"),
            _text_turn("user", "q2"),
            _text_turn("assistant", "a2"),
            _thinking_turn("assistant", "r3", "a3"),
            _text_turn("user", "q4"),
            _text_turn("assistant", "a4"),
        ]
        compacted = cc.compact_turns(original, max_turns=3)
        warnings = cc.validate_compaction(original, compacted)
        self.assertEqual(
            [],
            warnings,
            f"compact_turns should preserve thinking blocks but got: {warnings}",
        )


if __name__ == "__main__":
    unittest.main()
