"""
tests/unit/test_model_config.py
--------------------------------
Tests for bin/lib/model_config.py — the shared model configuration module.

All tests use tmp_path to create temporary JSON files.
No mocking required: the functions read real files.
"""

import json
import pytest

from model_config import load_merged_models, generate_custom_models


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_json(path, data):
    path.write_text(json.dumps(data))
    return str(path)


def make_model(id_, name, is_dry_run=False):
    return {"id": id_, "name": name, "is_dry_run": is_dry_run}


# ---------------------------------------------------------------------------
# Tests: load_merged_models
# ---------------------------------------------------------------------------


class TestLoadMergedModels:

    def test_base_only_no_custom(self, tmp_path):
        """Base JSON with 2 regular models + 1 dry-run, no custom path.
        Returns 3 models; dry-run is last."""
        base = write_json(tmp_path / "base.json", {"models": [
            make_model("model-a", "Model A"),
            make_model("dry-run", "Dry Run", is_dry_run=True),
            make_model("model-b", "Model B"),
        ]})

        result = load_merged_models(base)

        ids = [m["id"] for m in result]
        assert ids == ["model-a", "model-b", "dry-run"]
        assert result[-1]["is_dry_run"] is True

    def test_base_only_custom_path_missing(self, tmp_path):
        """Custom path given but file does not exist — falls back to base."""
        base = write_json(tmp_path / "base.json", {"models": [
            make_model("model-a", "Model A"),
            make_model("dry-run", "Dry Run", is_dry_run=True),
        ]})
        missing_custom = str(tmp_path / "does_not_exist.json")

        result = load_merged_models(base, missing_custom)

        ids = [m["id"] for m in result]
        assert ids == ["model-a", "dry-run"]

    def test_custom_overrides_base(self, tmp_path):
        """Custom present: only custom models returned; dry-run inherited from base."""
        base = write_json(tmp_path / "base.json", {"models": [
            make_model("model-a", "Model A"),
            make_model("model-b", "Model B"),
            make_model("dry-run-base", "Dry Run", is_dry_run=True),
        ]})
        custom = write_json(tmp_path / "custom.json", {"models": [
            make_model("model-x", "Model X"),
            make_model("model-y", "Model Y"),
        ]})

        result = load_merged_models(base, custom)

        ids = [m["id"] for m in result]
        # model-a and model-b must NOT be present
        assert "model-a" not in ids
        assert "model-b" not in ids
        # custom models present
        assert "model-x" in ids
        assert "model-y" in ids
        # base dry-run appended
        assert ids[-1] == "dry-run-base"

    def test_custom_has_own_dry_run(self, tmp_path):
        """Custom has its own dry-run — it takes priority over the base dry-run."""
        base = write_json(tmp_path / "base.json", {"models": [
            make_model("dry-run-base", "Dry Run Base", is_dry_run=True),
        ]})
        custom = write_json(tmp_path / "custom.json", {"models": [
            make_model("model-x", "Model X"),
            make_model("dry-run-custom", "Dry Run Custom", is_dry_run=True),
        ]})

        result = load_merged_models(base, custom)

        ids = [m["id"] for m in result]
        assert "dry-run-base" not in ids
        assert ids[-1] == "dry-run-custom"
        assert result[-1]["is_dry_run"] is True

    def test_custom_no_dry_run_inherits_from_base(self, tmp_path):
        """Custom has no dry-run; base dry-run is appended."""
        base = write_json(tmp_path / "base.json", {"models": [
            make_model("model-a", "Model A"),
            make_model("dry-run-base", "Dry Run Base", is_dry_run=True),
        ]})
        custom = write_json(tmp_path / "custom.json", {"models": [
            make_model("model-x", "Model X"),
        ]})

        result = load_merged_models(base, custom)

        ids = [m["id"] for m in result]
        assert ids[0] == "model-x"
        assert ids[-1] == "dry-run-base"

    def test_dry_run_name_suffix_not_duplicated(self, tmp_path):
        """Dry-run model whose name already contains '(dry run)' must NOT get a double suffix."""
        base = write_json(tmp_path / "base.json", {"models": [
            make_model("dr", "Test (dry run)", is_dry_run=True),
        ]})

        result = load_merged_models(base)

        assert result[0]["name"] == "Test (dry run)"

    def test_dry_run_name_suffix_appended(self, tmp_path):
        """Dry-run model without the suffix gets ' (dry run)' appended."""
        base = write_json(tmp_path / "base.json", {"models": [
            make_model("dr", "Test", is_dry_run=True),
        ]})

        result = load_merged_models(base)

        assert result[0]["name"] == "Test (dry run)"

    def test_empty_models(self, tmp_path):
        """Both files have empty models lists — returns empty list."""
        base = write_json(tmp_path / "base.json", {"models": []})
        custom = write_json(tmp_path / "custom.json", {"models": []})

        result = load_merged_models(base, custom)

        assert result == []

    def test_base_file_missing(self, tmp_path):
        """Non-existent base path raises FileNotFoundError."""
        missing = str(tmp_path / "nonexistent.json")

        with pytest.raises(FileNotFoundError):
            load_merged_models(missing)


# ---------------------------------------------------------------------------
# Tests: generate_custom_models
# ---------------------------------------------------------------------------

# Shared example data used by all generate tests
EXAMPLE_MODELS = [
    {"id": "claude-haiku", "name": "Claude Haiku", "is_dry_run": False},
    {"id": "gemini-pro",   "name": "Gemini Pro",   "is_dry_run": False},
    {"id": "gpt-4o",       "name": "GPT-4o",        "is_dry_run": False},
    {"id": "mistral-large","name": "Mistral Large", "is_dry_run": False},
    {"id": "o3-mini",      "name": "o3-mini",        "is_dry_run": False},
    {"id": "dry-run-dummy","name": "Dry Run",        "is_dry_run": True},
]


@pytest.fixture
def example_file(tmp_path):
    path = tmp_path / "models.example.json"
    path.write_text(json.dumps({"models": EXAMPLE_MODELS}))
    return str(path)


class TestGenerateCustomModels:

    def test_single_provider_anthropic(self, example_file):
        """Only claude-* models (+ dry-run) returned for anthropic provider."""
        result = generate_custom_models(example_file, providers=["anthropic"])

        ids = [m["id"] for m in result["models"]]
        assert "claude-haiku" in ids
        assert "gemini-pro" not in ids
        assert "gpt-4o" not in ids
        assert "mistral-large" not in ids
        assert "dry-run-dummy" in ids

    def test_multiple_providers(self, example_file):
        """anthropic + google returns claude-* and gemini-* models."""
        result = generate_custom_models(example_file, providers=["anthropic", "google"])

        ids = [m["id"] for m in result["models"]]
        assert "claude-haiku" in ids
        assert "gemini-pro" in ids
        assert "gpt-4o" not in ids
        assert "mistral-large" not in ids
        assert "dry-run-dummy" in ids

    def test_custom_endpoints_added(self, example_file):
        """Custom endpoint entries are appended with correct id/name/is_dry_run."""
        result = generate_custom_models(
            example_file,
            providers=["custom"],
            custom_names=["my-model"],
            custom_displays=["My Model"],
        )

        models = result["models"]
        custom_entry = next((m for m in models if m["id"] == "my-model"), None)
        assert custom_entry is not None
        assert custom_entry["name"] == "My Model"
        assert custom_entry["is_dry_run"] is False
        # Dry-run must still be present
        assert any(m["id"] == "dry-run-dummy" for m in models)

    def test_custom_display_falls_back_to_name(self, example_file):
        """When custom_displays is empty, the local ID is used as the display name."""
        result = generate_custom_models(
            example_file,
            providers=["custom"],
            custom_names=["my-model"],
            custom_displays=[],
        )

        custom_entry = next(m for m in result["models"] if m["id"] == "my-model")
        assert custom_entry["name"] == "my-model"

    def test_ollama_models_added(self, example_file):
        """Ollama entries use em-dash format 'Ollama — <name>'."""
        result = generate_custom_models(
            example_file,
            providers=["ollama"],
            ollama_models=["llama3.1", "mistral"],
        )

        models = result["models"]
        names = [m["name"] for m in models]
        assert "Ollama \u2014 llama3.1" in names
        assert "Ollama \u2014 mistral" in names
        # Dry-run must still be present
        assert any(m["id"] == "dry-run-dummy" for m in models)

    def test_dry_run_always_included(self, example_file):
        """Dry-run entry is always appended even if no provider prefix matches it."""
        result = generate_custom_models(example_file, providers=["anthropic"])

        assert any(m.get("is_dry_run") for m in result["models"])

    def test_no_providers_match(self, example_file):
        """No matching provider: only dry-run is returned."""
        result = generate_custom_models(example_file, providers=["nonexistent"])

        models = result["models"]
        assert len(models) == 1
        assert models[0]["id"] == "dry-run-dummy"

    def test_empty_custom_and_ollama(self, example_file):
        """custom/ollama providers with None names/models produce no extra entries."""
        result = generate_custom_models(
            example_file,
            providers=["custom", "ollama"],
            custom_names=None,
            ollama_models=None,
        )

        models = result["models"]
        # Only the dry-run entry (no prefix matches, no custom/ollama names given)
        ids = [m["id"] for m in models]
        assert ids == ["dry-run-dummy"]

    def test_openai_prefixes(self, example_file):
        """openai provider matches gpt-*, o3-*, o4-* prefixes."""
        result = generate_custom_models(example_file, providers=["openai"])

        ids = [m["id"] for m in result["models"]]
        assert "gpt-4o" in ids
        assert "o3-mini" in ids
        assert "claude-haiku" not in ids
