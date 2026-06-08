"""
Unit Tests: estimate_cost
--------------------------
Tests for services/toolbox/src/estimate_cost.py

Run command (inside toolbox container):
    docker compose exec toolbox python -m pytest /app/tests/unit/test_estimate_cost.py -v

Run command (on host, if shared/src is on PYTHONPATH):
    python -m pytest tests/unit/test_estimate_cost.py -v
"""
from __future__ import annotations

import math
import os
import sys

import pytest

# ---------------------------------------------------------------------------
# Path setup — mirrors the convention used in test_token_tracker.py
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/toolbox/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/shared/src")))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_po(tmp_path, filename: str, content: str):
    """Write a .po file to tmp_path and return its path."""
    p = tmp_path / filename
    p.write_text(content, encoding="utf-8")
    return str(p)


def _simple_po(entries: list[tuple[str, str]]) -> str:
    """Build a minimal .po file string from (msgid, msgstr) pairs."""
    header = (
        'msgid ""\n'
        'msgstr ""\n'
        '"Language: ja\\n"\n'
        '"Content-Type: text/plain; charset=UTF-8\\n"\n'
    )
    body = "\n\n".join(
        f'msgid "{msgid}"\nmsgstr "{msgstr}"'
        for msgid, msgstr in entries
    )
    return header + "\n\n" + body


# ---------------------------------------------------------------------------
# count_and_estimate
# ---------------------------------------------------------------------------

class TestCountAndEstimate:
    """Tests for count_and_estimate()."""

    def test_empty_directory_returns_zeros(self, tmp_path):
        """No .po files in the directory → all outputs are 0."""
        from estimate_cost import count_and_estimate
        slots, batches, tokens = count_and_estimate(str(tmp_path), "ja", 15)
        assert slots == 0
        assert batches == 0
        assert tokens == 0

    def test_counts_untranslated_entries(self, tmp_path):
        """Only entries with empty msgstr are counted as needing translation."""
        from estimate_cost import count_and_estimate
        po = _simple_po([
            ("Hello", ""),       # untranslated
            ("World", ""),       # untranslated
            ("Done", "完了"),    # already translated — must NOT be counted
        ])
        _write_po(tmp_path, "test.po", po)
        slots, batches, tokens = count_and_estimate(str(tmp_path), "ja", 15)
        assert slots == 2

    def test_counts_fuzzy_entries(self, tmp_path):
        """Entries flagged as fuzzy need re-translation and must be counted."""
        from estimate_cost import count_and_estimate
        po = (
            'msgid ""\nmsgstr ""\n"Language: ja\\n"\n\n'
            "#, fuzzy\n"
            'msgid "Fuzzy string"\n'
            'msgstr "ファジー"\n'
        )
        _write_po(tmp_path, "test.po", po)
        slots, batches, tokens = count_and_estimate(str(tmp_path), "ja", 15)
        assert slots == 1

    def test_fully_translated_file_returns_zero_slots(self, tmp_path):
        """A file where every entry is translated contributes 0 slots."""
        from estimate_cost import count_and_estimate
        po = _simple_po([("Hello", "こんにちは"), ("World", "世界")])
        _write_po(tmp_path, "test.po", po)
        slots, batches, tokens = count_and_estimate(str(tmp_path), "ja", 15)
        assert slots == 0
        assert batches == 0
        assert tokens == 0

    def test_batch_count_rounds_up(self, tmp_path):
        """Batch count = ceil(total_slots / bulk_size)."""
        from estimate_cost import count_and_estimate
        # 20 untranslated entries, bulk_size=15 → ceil(20/15) = 2
        entries = [(f"String {i}", "") for i in range(20)]
        _write_po(tmp_path, "test.po", _simple_po(entries))
        slots, batches, tokens = count_and_estimate(str(tmp_path), "ja", 15)
        assert slots == 20
        assert batches == math.ceil(20 / 15)

    def test_batch_count_exact_multiple(self, tmp_path):
        """When slots divide evenly, batch count is exact (not rounded up)."""
        from estimate_cost import count_and_estimate
        entries = [(f"String {i}", "") for i in range(15)]
        _write_po(tmp_path, "test.po", _simple_po(entries))
        slots, batches, _ = count_and_estimate(str(tmp_path), "ja", 15)
        assert slots == 15
        assert batches == 1

    def test_input_tokens_positive_for_nonempty_input(self, tmp_path):
        """At least some tokens are estimated when there are entries to translate."""
        from estimate_cost import count_and_estimate
        _write_po(tmp_path, "test.po", _simple_po([("Hello world", "")]))
        _, _, tokens = count_and_estimate(str(tmp_path), "ja", 15)
        assert tokens > 0

    def test_multiple_po_files_are_aggregated(self, tmp_path):
        """Slots from multiple .po files in the same directory are summed."""
        from estimate_cost import count_and_estimate
        _write_po(tmp_path, "file1.po", _simple_po([("A", ""), ("B", "")]))
        _write_po(tmp_path, "file2.po", _simple_po([("C", ""), ("D", "")]))
        slots, _, _ = count_and_estimate(str(tmp_path), "ja", 15)
        assert slots == 4

    def test_unreadable_file_is_skipped_gracefully(self, tmp_path):
        """A corrupted .po file is logged and skipped; other files still process."""
        from estimate_cost import count_and_estimate
        _write_po(tmp_path, "bad.po", "this is not valid po content !!!")
        _write_po(tmp_path, "good.po", _simple_po([("Valid", "")]))
        # Should not raise; good file contributes its slot
        slots, _, _ = count_and_estimate(str(tmp_path), "ja", 15)
        # bad.po is skipped, good.po contributes 1
        assert slots == 1


# ---------------------------------------------------------------------------
# compute_cost_range
# ---------------------------------------------------------------------------

class TestComputeCostRange:
    """Tests for compute_cost_range()."""

    def test_returns_none_when_both_rates_missing(self):
        from estimate_cost import compute_cost_range
        assert compute_cost_range(1000, None, None) == (None, None)

    def test_returns_none_when_prompt_rate_missing(self):
        from estimate_cost import compute_cost_range
        assert compute_cost_range(1000, None, 0.03) == (None, None)

    def test_returns_none_when_completion_rate_missing(self):
        from estimate_cost import compute_cost_range
        assert compute_cost_range(1000, 0.01, None) == (None, None)

    def test_computes_cost_range_correctly(self):
        """Verify arithmetic: 10K tokens at $0.01/1k prompt + $0.03/1k completion."""
        from estimate_cost import compute_cost_range
        low, high = compute_cost_range(10_000, 0.01, 0.03)
        # low:  (10000/1000 * 0.01) + (10000/1000 * 0.03) = 0.10 + 0.30 = 0.40
        # high: (10000/1000 * 0.01) + (20000/1000 * 0.03) = 0.10 + 0.60 = 0.70
        assert low == pytest.approx(0.40, abs=1e-4)
        assert high == pytest.approx(0.70, abs=1e-4)

    def test_low_is_always_lte_high(self):
        """Low bound must never exceed high bound."""
        from estimate_cost import compute_cost_range
        low, high = compute_cost_range(5000, 0.015, 0.075)
        assert low is not None
        assert high is not None
        assert low <= high

    def test_zero_tokens_returns_zero_cost(self):
        """Zero input tokens → $0 both bounds (not None)."""
        from estimate_cost import compute_cost_range
        low, high = compute_cost_range(0, 0.01, 0.03)
        assert low == pytest.approx(0.0)
        assert high == pytest.approx(0.0)

    def test_result_is_rounded_to_four_decimal_places(self):
        """Results should not have more than 4 decimal places."""
        from estimate_cost import compute_cost_range
        low, high = compute_cost_range(333, 0.003, 0.009)
        # Verify rounding occurred (not checking the exact value, just precision)
        assert low == round(low, 4)
        assert high == round(high, 4)
