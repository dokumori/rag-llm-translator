"""
Unit Test: Shared Config – load_models_config
----------------------------------------------
Tests the model configuration loading and merging logic in core/config.py.
Covers: base-only loading, custom overrides, dry-run preservation, and error handling.

Run Command:
    bash bin/run_tests.sh tests/unit/test_config.py -v
"""
import json
import pytest
from unittest.mock import patch, mock_open, call
from core.config import load_models_config


# ---------------------------------------------------------------------------
# Helpers – build JSON strings that mirror the real models.json format
# ---------------------------------------------------------------------------

def _models_json(models: list) -> str:
    return json.dumps({"models": models})


BASE_MODELS = [
    {"id": "model-a", "name": "Model A", "is_dry_run": False},
    {"id": "model-b", "name": "Model B", "is_dry_run": False},
    {"id": "dry-run-model", "name": "Dry Run", "is_dry_run": True},
]

CUSTOM_MODELS = [
    {"id": "custom-1", "name": "Custom 1", "is_dry_run": False},
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestLoadModelsConfigBaseOnly:
    """Scenarios where NO custom override file exists."""

    def test_returns_base_models_when_no_custom_file(self, tmp_path):
        """With only a base file present, all base models are returned."""
        base_file = tmp_path / "models.json"
        base_file.write_text(_models_json(BASE_MODELS))

        result = load_models_config(
            models_path=str(base_file),
            custom_path=str(tmp_path / "nonexistent.json"),
        )

        assert len(result) == 3
        ids = [m["id"] for m in result]
        assert "model-a" in ids
        assert "dry-run-model" in ids

    def test_returns_empty_list_when_base_missing(self, tmp_path):
        """If the base file is also missing, return an empty list (no crash)."""
        result = load_models_config(
            models_path=str(tmp_path / "missing.json"),
            custom_path=str(tmp_path / "also_missing.json"),
        )

        assert result == []

    def test_returns_empty_on_malformed_base_json(self, tmp_path):
        """A corrupted base file should not crash; returns empty list."""
        bad_file = tmp_path / "models.json"
        bad_file.write_text("{not valid json!!!")

        result = load_models_config(
            models_path=str(bad_file),
            custom_path=str(tmp_path / "nonexistent.json"),
        )

        assert result == []


class TestLoadModelsConfigCustomOverride:
    """Scenarios where a custom override file IS present."""

    def test_custom_replaces_base_and_preserves_dry_run(self, tmp_path):
        """
        When a custom file exists, its models replace base models entirely.
        The dry-run model from the base file is auto-appended if not already
        present in the custom list.
        """
        base_file = tmp_path / "models.json"
        base_file.write_text(_models_json(BASE_MODELS))

        custom_file = tmp_path / "custom.json"
        custom_file.write_text(_models_json(CUSTOM_MODELS))

        result = load_models_config(
            models_path=str(base_file),
            custom_path=str(custom_file),
        )

        ids = [m["id"] for m in result]
        # Custom model is present
        assert "custom-1" in ids
        # Base-only models are NOT carried over
        assert "model-a" not in ids
        assert "model-b" not in ids
        # Dry-run model from base IS auto-appended
        assert "dry-run-model" in ids
        assert len(result) == 2  # custom-1 + dry-run-model

    def test_no_duplicate_dry_run_when_custom_includes_it(self, tmp_path):
        """
        If the custom file already defines the dry-run model id,
        it should NOT be appended again from the base config.
        """
        base_file = tmp_path / "models.json"
        base_file.write_text(_models_json(BASE_MODELS))

        custom_with_dry = [
            {"id": "custom-1", "name": "Custom 1", "is_dry_run": False},
            {"id": "dry-run-model", "name": "Custom Dry Run", "is_dry_run": True},
        ]
        custom_file = tmp_path / "custom.json"
        custom_file.write_text(_models_json(custom_with_dry))

        result = load_models_config(
            models_path=str(base_file),
            custom_path=str(custom_file),
        )

        ids = [m["id"] for m in result]
        # Exactly 2 entries, no duplicate dry-run
        assert ids.count("dry-run-model") == 1
        assert len(result) == 2

    def test_custom_without_base_dry_run(self, tmp_path):
        """
        If the base config has no dry-run model, custom models are returned
        as-is with nothing extra appended.
        """
        base_no_dry = [
            {"id": "model-a", "name": "Model A", "is_dry_run": False},
        ]
        base_file = tmp_path / "models.json"
        base_file.write_text(_models_json(base_no_dry))

        custom_file = tmp_path / "custom.json"
        custom_file.write_text(_models_json(CUSTOM_MODELS))

        result = load_models_config(
            models_path=str(base_file),
            custom_path=str(custom_file),
        )

        assert len(result) == 1
        assert result[0]["id"] == "custom-1"

    def test_malformed_custom_falls_back_to_base(self, tmp_path):
        """
        If the custom file exists but is corrupted, the function should
        gracefully fall back to the base models.
        """
        base_file = tmp_path / "models.json"
        base_file.write_text(_models_json(BASE_MODELS))

        bad_custom = tmp_path / "custom.json"
        bad_custom.write_text("<<< not json >>>")

        result = load_models_config(
            models_path=str(base_file),
            custom_path=str(bad_custom),
        )

        assert len(result) == 3
        ids = [m["id"] for m in result]
        assert "model-a" in ids

    def test_empty_custom_models_list(self, tmp_path):
        """
        A valid custom file with an empty models array should return just
        the dry-run model (if one exists in base).
        """
        base_file = tmp_path / "models.json"
        base_file.write_text(_models_json(BASE_MODELS))

        custom_file = tmp_path / "custom.json"
        custom_file.write_text(_models_json([]))

        result = load_models_config(
            models_path=str(base_file),
            custom_path=str(custom_file),
        )

        # Only the auto-appended dry-run model
        assert len(result) == 1
        assert result[0]["id"] == "dry-run-model"
