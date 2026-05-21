"""
Unit Test: Shared Config – load_models_config
----------------------------------------------
Tests the model configuration loading logic in core/config.py.
Covers: YAML loading, ordering, dry-run handling, and error handling.

Run Command:
    bash bin/run_tests.sh tests/unit/test_config.py -v
"""
import pytest
import yaml
from core.config import load_models_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_yaml(path, models: list) -> str:
    path.write_text(yaml.dump({"models": models}, default_flow_style=False))
    return str(path)


def _make(id_, name, is_dry_run=False):
    m = {"id": id_, "name": name, "is_dry_run": is_dry_run}
    if not is_dry_run:
        m["provider"] = "anthropic"
        m["model"] = id_
        m["api_key_env"] = "ANTHROPIC_API_KEY"
    return m


BASE_MODELS = [
    _make("model-a", "Model A"),
    _make("model-b", "Model B"),
    _make("dry-run-model", "Dry Run", is_dry_run=True),
]


# ---------------------------------------------------------------------------
# Tests: YAML loading
# ---------------------------------------------------------------------------

class TestLoadModelsConfigYaml:

    def test_loads_from_yaml_file(self, tmp_path):
        """Loads models from a valid YAML file, returning all entries."""
        f = _write_yaml(tmp_path / "models.yaml", BASE_MODELS)
        result = load_models_config(models_path=f)
        assert len(result) == 3
        ids = [m["id"] for m in result]
        assert "model-a" in ids
        assert "dry-run-model" in ids

    def test_dry_run_ordered_last(self, tmp_path):
        """Dry-run model is always placed at the end of the list."""
        models = [
            _make("dry-run", "Dry Run", is_dry_run=True),
            _make("model-a", "Model A"),
        ]
        f = _write_yaml(tmp_path / "models.yaml", models)
        result = load_models_config(models_path=f)
        assert result[-1]["id"] == "dry-run"
        assert result[-1]["is_dry_run"] is True

    def test_returns_empty_list_when_file_missing(self, tmp_path):
        """Missing file logs a warning and returns empty list (no crash)."""
        result = load_models_config(models_path=str(tmp_path / "missing.yaml"))
        assert result == []

    def test_returns_empty_on_malformed_yaml(self, tmp_path):
        """Corrupted YAML logs an error and returns empty list (no crash)."""
        bad = tmp_path / "models.yaml"
        bad.write_text("{not: valid: yaml: [[[")
        result = load_models_config(models_path=str(bad))
        assert result == []

    def test_empty_models_list_returns_empty(self, tmp_path):
        """A valid YAML file with an empty models list returns []."""
        f = _write_yaml(tmp_path / "models.yaml", [])
        result = load_models_config(models_path=f)
        assert result == []

    def test_pricing_fields_preserved(self, tmp_path):
        """Pricing metadata survives loading unchanged."""
        models = [{**_make("m", "M"), "pricing": {
            "prompt_per_1k_tokens": 0.003,
            "completion_per_1k_tokens": 0.015,
        }}]
        f = _write_yaml(tmp_path / "models.yaml", models)
        result = load_models_config(models_path=f)
        assert result[0]["pricing"]["completion_per_1k_tokens"] == pytest.approx(0.015)

    def test_uses_default_path_env_var(self, tmp_path, monkeypatch):
        """MODELS_CONFIG_PATH env var controls the default path."""
        f = _write_yaml(tmp_path / "models.yaml", BASE_MODELS)
        monkeypatch.setenv("MODELS_CONFIG_PATH", f)
        # Re-evaluate Config class attribute by patching at call time
        import core.config as cfg_mod
        original = cfg_mod.Config.MODELS_CONFIG_PATH
        cfg_mod.Config.MODELS_CONFIG_PATH = f
        try:
            result = load_models_config()  # no explicit path
            assert len(result) == 3
        finally:
            cfg_mod.Config.MODELS_CONFIG_PATH = original


# ---------------------------------------------------------------------------
# Tests for _validate_model_flags
# ---------------------------------------------------------------------------

class TestValidateModelFlags:

    def test_warns_when_flag_is_string_instead_of_bool(self, tmp_path, caplog):
        """_validate_model_flags must emit a warning when is_dry_run is a string."""
        import logging
        bad = [{
            "id": "bad-model", "name": "Bad",
            "provider": "anthropic", "model": "bad", "api_key_env": "KEY",
            "is_dry_run": "false",   # string, not bool
        }]
        f = _write_yaml(tmp_path / "models.yaml", bad)
        with caplog.at_level(logging.WARNING):
            load_models_config(models_path=f)
        assert any("bad-model" in r.message and "is_dry_run" in r.message
                   for r in caplog.records)

    def test_no_warning_for_correct_booleans(self, tmp_path, caplog):
        """_validate_model_flags must be silent for correctly typed boolean flags."""
        import logging
        good = [_make("good-model", "Good")]
        f = _write_yaml(tmp_path / "models.yaml", good)
        with caplog.at_level(logging.WARNING):
            load_models_config(models_path=f)
        flag_warnings = [r for r in caplog.records if "good-model" in r.message]
        assert not flag_warnings
