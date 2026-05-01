"""
Unit Tests: TokenTracker
------------------------
Tests for services/shared/src/core/token_tracker.py

Run command:
    docker compose exec toolbox python -m pytest /app/tests/unit/test_token_tracker.py
"""
import json
import os
import sys
import pytest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/shared/src")))

from core.token_tracker import TokenTracker, build_price_table_from_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_usage(prompt: int, completion: int, total: int = None):
    """Return a MagicMock mimicking an openai CompletionUsage object."""
    m = MagicMock()
    m.prompt_tokens = prompt
    m.completion_tokens = completion
    m.total_tokens = total if total is not None else (prompt + completion)
    return m


def _make_usage_dict(prompt: int, completion: int, total: int = None):
    """Return a dict mimicking a usage payload."""
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total if total is not None else (prompt + completion),
    }


# ---------------------------------------------------------------------------
# build_price_table_from_config
# ---------------------------------------------------------------------------

class TestBuildPriceTableFromConfig:
    def test_extracts_pricing_from_model_entries(self):
        """A model entry with a valid 'pricing' block is included in the returned table."""
        models = [
            {
                "id": "my-model-v1",
                "name": "My Model",
                "pricing": {
                    "prompt_per_1k_tokens": 0.01,
                    "completion_per_1k_tokens": 0.03,
                },
            }
        ]
        table = build_price_table_from_config(models)
        assert "my-model-v1" in table
        assert table["my-model-v1"] == (0.01, 0.03)

    def test_skips_entries_without_pricing(self):
        """A model entry with no 'pricing' key is silently excluded from the table."""
        models = [{"id": "no-pricing-model", "name": "No Pricing"}]
        table = build_price_table_from_config(models)
        assert "no-pricing-model" not in table

    def test_skips_entries_with_partial_pricing(self):
        """Both rates must be present; a partial entry is skipped."""
        models = [
            {
                "id": "partial-model",
                "pricing": {"prompt_per_1k_tokens": 0.01},  # missing completion
            }
        ]
        table = build_price_table_from_config(models)
        assert "partial-model" not in table

    def test_skips_entries_without_id(self):
        """A pricing entry with no 'id' field is excluded — the table would have no key to store it under."""
        models = [{"pricing": {"prompt_per_1k_tokens": 0.01, "completion_per_1k_tokens": 0.03}}]
        table = build_price_table_from_config(models)
        assert table == {}

    def test_coerces_string_values_to_float(self):
        """Pricing values supplied as JSON strings are cast to float without error."""
        models = [
            {
                "id": "string-price-model",
                "pricing": {
                    "prompt_per_1k_tokens": "0.005",
                    "completion_per_1k_tokens": "0.015",
                },
            }
        ]
        table = build_price_table_from_config(models)
        assert table["string-price-model"] == (0.005, 0.015)

    def test_skips_entry_with_invalid_price_values(self, caplog):
        import logging
        models = [
            {
                "id": "bad-price-model",
                "pricing": {
                    "prompt_per_1k_tokens": "not-a-number",
                    "completion_per_1k_tokens": 0.015,
                },
            }
        ]
        with caplog.at_level(logging.WARNING):
            table = build_price_table_from_config(models)
        assert "bad-price-model" not in table
        assert "Invalid pricing" in caplog.text

    def test_processes_multiple_models(self):
        """All models with valid pricing are included; models without pricing are silently skipped."""
        models = [
            {"id": "model-a", "pricing": {"prompt_per_1k_tokens": 0.01, "completion_per_1k_tokens": 0.03}},
            {"id": "model-b", "pricing": {"prompt_per_1k_tokens": 0.005, "completion_per_1k_tokens": 0.015}},
            {"id": "model-c"},  # no pricing
        ]
        table = build_price_table_from_config(models)
        assert len(table) == 2
        assert "model-c" not in table

    def test_empty_list_returns_empty_dict(self):
        """An empty models list produces an empty price table without raising."""
        assert build_price_table_from_config([]) == {}

    def test_dry_run_model_without_pricing_is_skipped(self):
        """Dry-run models typically have no pricing; they must not appear in the table."""
        models = [{"id": "dry-run-model", "name": "Dry Run", "is_dry_run": True}]
        table = build_price_table_from_config(models)
        assert "dry-run-model" not in table


# ---------------------------------------------------------------------------
# record()
# ---------------------------------------------------------------------------

class TestRecord:
    def test_accumulates_tokens_from_sdk_object(self):
        """Token counts from multiple SDK response objects are summed across calls."""
        tracker = TokenTracker(model="test-model")
        tracker.record(_make_usage(100, 50))
        tracker.record(_make_usage(200, 75))
        assert tracker.prompt_tokens == 300
        assert tracker.completion_tokens == 125
        assert tracker.total_tokens == 425
        assert tracker.request_count == 2

    def test_accumulates_tokens_from_dict(self):
        """record() accepts a plain dict in addition to SDK objects."""
        tracker = TokenTracker(model="test-model")
        tracker.record(_make_usage_dict(80, 20))
        assert tracker.prompt_tokens == 80
        assert tracker.completion_tokens == 20
        assert tracker.total_tokens == 100
        assert tracker.request_count == 1

    def test_none_usage_is_silently_skipped(self):
        """Dry-run responses return usage=None; that must not raise."""
        tracker = TokenTracker(model="test-model")
        tracker.record(None)
        assert tracker.request_count == 0
        assert tracker.total_tokens == 0

    def test_missing_total_tokens_is_derived(self):
        """If total_tokens is 0/None on the usage object, derive from p + c."""
        usage = _make_usage(50, 30, total=0)
        tracker = TokenTracker(model="test-model")
        tracker.record(usage)
        assert tracker.total_tokens == 80

    def test_zero_usage_increments_request_count(self):
        """A response that consumed 0 tokens still counts as a request."""
        tracker = TokenTracker(model="test-model")
        tracker.record(_make_usage(0, 0, total=0))
        assert tracker.request_count == 1


# ---------------------------------------------------------------------------
# estimated_cost_usd()
# ---------------------------------------------------------------------------

class TestEstimatedCost:
    def test_returns_cost_when_pricing_supplied(self):
        """estimated_cost_usd() returns a non-zero float when both rates are set."""
        tracker = TokenTracker(
            model="my-model",
            cost_per_1k_prompt=0.01,
            cost_per_1k_completion=0.03,
        )
        tracker.record(_make_usage(1000, 1000))
        assert tracker.estimated_cost_usd() == pytest.approx(0.04)

    def test_returns_none_when_no_pricing_supplied(self):
        """estimated_cost_usd() returns None when the tracker was constructed without rates."""
        tracker = TokenTracker(model="my-model")  # no pricing
        tracker.record(_make_usage(1000, 1000))
        assert tracker.estimated_cost_usd() is None

    def test_returns_none_when_only_prompt_rate_supplied(self):
        """Both rates must be present; supplying only one still returns None."""
        tracker = TokenTracker(model="my-model", cost_per_1k_prompt=0.01)
        tracker.record(_make_usage(1000, 500))
        assert tracker.estimated_cost_usd() is None

    def test_cost_calculation_is_correct(self):
        """$0.015/1k prompt + $0.075/1k completion."""
        tracker = TokenTracker(
            model="claude-opus-4",
            cost_per_1k_prompt=0.015,
            cost_per_1k_completion=0.075,
        )
        tracker.record(_make_usage(2000, 1000))
        # (2000/1000 * 0.015) + (1000/1000 * 0.075) = 0.03 + 0.075 = 0.105
        assert tracker.estimated_cost_usd() == pytest.approx(0.105)

    def test_zero_tokens_returns_zero_cost(self):
        """Zero token usage with valid rates produces $0.00 — not None."""
        tracker = TokenTracker(
            model="my-model",
            cost_per_1k_prompt=0.01,
            cost_per_1k_completion=0.03,
        )
        assert tracker.estimated_cost_usd() == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Integration: build_price_table_from_config → TokenTracker
# ---------------------------------------------------------------------------

class TestPricingIntegration:
    def test_tracker_gets_pricing_from_config(self):
        """End-to-end: build_price_table_from_config feeds correct rates into TokenTracker."""
        models = [
            {
                "id": "my-exact-model-id",
                "pricing": {
                    "prompt_per_1k_tokens": 0.01,
                    "completion_per_1k_tokens": 0.03,
                },
            }
        ]
        table = build_price_table_from_config(models)
        prompt_rate, completion_rate = table.get("my-exact-model-id", (None, None))
        tracker = TokenTracker(
            model="my-exact-model-id",
            cost_per_1k_prompt=prompt_rate,
            cost_per_1k_completion=completion_rate,
        )
        tracker.record(_make_usage(1000, 500))
        assert tracker.estimated_cost_usd() == pytest.approx(0.025)  # 0.01 + 0.015

    def test_tracker_has_no_cost_when_model_not_in_config(self):
        """When a model ID is absent from the config table, the tracker has no cost data."""
        table = build_price_table_from_config([])
        prompt_rate, completion_rate = table.get("unknown-model", (None, None))
        tracker = TokenTracker(
            model="unknown-model",
            cost_per_1k_prompt=prompt_rate,
            cost_per_1k_completion=completion_rate,
        )
        tracker.record(_make_usage(1000, 500))
        assert tracker.estimated_cost_usd() is None


# ---------------------------------------------------------------------------
# summary_lines() / print_summary()
# ---------------------------------------------------------------------------

class TestSummaryLines:
    def test_contains_model_name(self):
        """The model ID string appears in the formatted summary output."""
        tracker = TokenTracker(model="my-model-v1")
        tracker.record(_make_usage(100, 50))
        lines = "\n".join(tracker.summary_lines())
        assert "my-model-v1" in lines

    def test_contains_token_counts(self):
        """Prompt and completion token counts appear in the summary, formatted with commas."""
        tracker = TokenTracker(model="test")
        tracker.record(_make_usage(1234, 567))
        lines = "\n".join(tracker.summary_lines())
        assert "1,234" in lines
        assert "567" in lines

    def test_cost_line_present_when_pricing_supplied(self):
        """A '$' cost figure appears in the summary when pricing rates are configured."""
        tracker = TokenTracker(
            model="my-model",
            cost_per_1k_prompt=0.01,
            cost_per_1k_completion=0.03,
        )
        tracker.record(_make_usage(1000, 500))
        lines = "\n".join(tracker.summary_lines())
        assert "$" in lines

    def test_cost_line_shows_guidance_when_no_pricing(self):
        """When no pricing is set, the summary directs the user to models.json instead of showing N/A."""
        tracker = TokenTracker(model="unknown-model")
        tracker.record(_make_usage(100, 50))
        lines = "\n".join(tracker.summary_lines())
        assert "models.json" in lines

    def test_print_summary_logs_no_request_message_when_empty(self, caplog):
        import logging
        tracker = TokenTracker(model="test")
        with caplog.at_level(logging.INFO):
            tracker.print_summary()
        assert "No LLM requests" in caplog.text


# ---------------------------------------------------------------------------
# to_dict()
# ---------------------------------------------------------------------------

class TestToDict:
    def test_returns_expected_keys(self):
        """to_dict() output contains all required JSON keys for downstream persistence."""
        tracker = TokenTracker(model="my-model")
        tracker.record(_make_usage(100, 50))
        d = tracker.to_dict()
        for key in ("timestamp", "model", "request_count",
                     "prompt_tokens", "completion_tokens",
                     "total_tokens", "estimated_cost_usd"):
            assert key in d, f"Missing key: {key}"

    def test_values_are_correct(self):
        """to_dict() values match the token counts recorded via record()."""
        tracker = TokenTracker(model="my-model")
        tracker.record(_make_usage(200, 100))
        d = tracker.to_dict()
        assert d["model"] == "my-model"
        assert d["prompt_tokens"] == 200
        assert d["completion_tokens"] == 100
        assert d["total_tokens"] == 300
        assert d["request_count"] == 1

    def test_is_json_serializable(self):
        """to_dict() output can be passed to json.dumps() without raising."""
        tracker = TokenTracker(model="my-model")
        tracker.record(_make_usage(50, 25))
        # Must not raise
        json.dumps(tracker.to_dict())

    def test_estimated_cost_usd_is_none_when_no_pricing(self):
        """estimated_cost_usd is serialised as JSON null when no pricing rates are set."""
        tracker = TokenTracker(model="my-model")
        tracker.record(_make_usage(100, 50))
        assert tracker.to_dict()["estimated_cost_usd"] is None

    def test_estimated_cost_usd_is_float_when_pricing_set(self):
        """estimated_cost_usd is a float (not None) in the dict when pricing is configured."""
        tracker = TokenTracker(
            model="my-model",
            cost_per_1k_prompt=0.01,
            cost_per_1k_completion=0.03,
        )
        tracker.record(_make_usage(100, 50))
        assert isinstance(tracker.to_dict()["estimated_cost_usd"], float)


# ---------------------------------------------------------------------------
# save()
# ---------------------------------------------------------------------------

class TestSave:
    def test_saves_valid_json_to_file(self, tmp_path):
        """save() writes a valid JSON file containing the expected model and token data."""
        tracker = TokenTracker(model="my-model")
        tracker.record(_make_usage(100, 50))
        path = str(tmp_path / "usage.json")
        tracker.save(path)
        assert os.path.exists(path)
        with open(path) as f:
            data = json.load(f)
        assert data["model"] == "my-model"
        assert data["total_tokens"] == 150

    def test_saves_to_directory_with_generated_filename(self, tmp_path):
        """Passing a directory path auto-generates a timestamped 'token_usage_*.json' filename."""
        tracker = TokenTracker(model="my-model")
        tracker.record(_make_usage(10, 5))
        tracker.save(str(tmp_path))
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        assert files[0].name.startswith("token_usage_")
        assert files[0].suffix == ".json"

    def test_creates_parent_directories(self, tmp_path):
        """save() creates any missing parent directories rather than raising FileNotFoundError."""
        tracker = TokenTracker(model="my-model")
        tracker.record(_make_usage(1, 1))
        deep = str(tmp_path / "a" / "b" / "c" / "usage.json")
        tracker.save(deep)
        assert os.path.exists(deep)

    def test_save_logs_warning_on_permission_error(self, tmp_path, caplog):
        """If the file cannot be written, a warning is logged (no crash)."""
        import logging
        tracker = TokenTracker(model="test")
        tracker.record(_make_usage(10, 5))
        bad_path = "/proc/non_existent_dir/usage.json"  # unwritable on Linux/macOS
        with caplog.at_level(logging.WARNING):
            tracker.save(bad_path)
        assert "Could not save" in caplog.text
