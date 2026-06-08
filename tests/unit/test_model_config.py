"""
tests/unit/test_model_config.py
--------------------------------
Tests for bin/lib/model_config.py — the shared model configuration module.

All tests use tmp_path to create temporary YAML files.
No mocking required: the functions read real files.
"""

import pytest
import yaml

from model_config import (
    load_models_yaml,
    generate_litellm_config,
    generate_models_yaml,
    _BLOCKED_MODEL_PATTERNS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_yaml(path, data):
    path.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")
    return str(path)


def make_model(id_, name, is_dry_run=False, provider="anthropic", **kwargs):
    m = {"id": id_, "name": name, "is_dry_run": is_dry_run}
    if not is_dry_run:
        m["provider"] = provider
        m["model"] = id_
        m["api_key_env"] = "ANTHROPIC_API_KEY"
    m.update(kwargs)
    return m


# ---------------------------------------------------------------------------
# Tests: load_models_yaml
# ---------------------------------------------------------------------------


class TestLoadModelsYaml:

    def test_basic_load(self, tmp_path):
        """Loads regular and dry-run models; dry-run is last."""
        f = write_yaml(tmp_path / "models.yaml", {"models": [
            make_model("model-a", "Model A"),
            make_model("dry-run", "Dry Run", is_dry_run=True),
            make_model("model-b", "Model B"),
        ]})
        result = load_models_yaml(f)
        ids = [m["id"] for m in result]
        assert ids == ["model-a", "model-b", "dry-run"]
        assert result[-1]["is_dry_run"] is True

    def test_dry_run_suffix_appended(self, tmp_path):
        """Dry-run entry without suffix gets ' (dry run)' appended."""
        f = write_yaml(tmp_path / "models.yaml", {"models": [
            make_model("dr", "My Sentinel", is_dry_run=True),
        ]})
        result = load_models_yaml(f)
        assert result[0]["name"] == "My Sentinel (dry run)"

    def test_dry_run_suffix_not_duplicated(self, tmp_path):
        """Dry-run entry whose name already contains '(dry run)' is left unchanged."""
        f = write_yaml(tmp_path / "models.yaml", {"models": [
            make_model("dr", "Already (dry run)", is_dry_run=True),
        ]})
        result = load_models_yaml(f)
        assert result[0]["name"] == "Already (dry run)"

    def test_file_not_found_raises(self, tmp_path):
        """Non-existent path raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_models_yaml(str(tmp_path / "nonexistent.yaml"))

    def test_empty_models_list(self, tmp_path):
        """Empty models list returns empty result."""
        f = write_yaml(tmp_path / "models.yaml", {"models": []})
        assert load_models_yaml(f) == []

    def test_pricing_preserved(self, tmp_path):
        """Pricing fields survive round-trip through load_models_yaml."""
        f = write_yaml(tmp_path / "models.yaml", {"models": [
            {**make_model("m", "M"), "pricing": {
                "prompt_per_1k_tokens": 0.003,
                "completion_per_1k_tokens": 0.015,
            }},
        ]})
        result = load_models_yaml(f)
        assert result[0]["pricing"]["prompt_per_1k_tokens"] == pytest.approx(0.003)


# ---------------------------------------------------------------------------
# Tests: generate_litellm_config
# ---------------------------------------------------------------------------


class TestGenerateLitellmConfig:

    def _load_yaml(self, path):
        return yaml.safe_load(open(path).read())

    def test_basic_anthropic(self, tmp_path):
        """Anthropic model maps to anthropic/<model> with api_key."""
        src = write_yaml(tmp_path / "models.yaml", {"models": [
            make_model("claude-haiku-4-5", "Claude Haiku", provider="anthropic"),
            make_model("dry-run-dummy", "Dry Run", is_dry_run=True),
        ]})
        out = str(tmp_path / "config.yaml")
        generate_litellm_config(src, out)

        cfg = self._load_yaml(out)
        ml = cfg["model_list"]
        assert len(ml) == 1  # dry-run excluded
        assert ml[0]["model_name"] == "claude-haiku-4-5"
        assert ml[0]["litellm_params"]["model"] == "anthropic/claude-haiku-4-5"
        assert ml[0]["litellm_params"]["api_key"] == "os.environ/ANTHROPIC_API_KEY"

    def test_google_model(self, tmp_path):
        """Google provider maps to gemini/<model>."""
        src = write_yaml(tmp_path / "models.yaml", {"models": [
            {**make_model("gemini-3.5-flash", "Gemini Flash", provider="google"),
             "model": "gemini-3.5-flash", "api_key_env": "GEMINI_API_KEY"},
        ]})
        out = str(tmp_path / "config.yaml")
        generate_litellm_config(src, out)

        cfg = self._load_yaml(out)
        params = cfg["model_list"][0]["litellm_params"]
        assert params["model"] == "gemini/gemini-3.5-flash"
        assert params["api_key"] == "os.environ/GEMINI_API_KEY"

    def test_custom_provider_uses_openai_prefix(self, tmp_path):
        """Custom provider maps to openai/<model> with both api_key and api_base."""
        src = write_yaml(tmp_path / "models.yaml", {"models": [
            {"id": "my-endpoint", "name": "My Endpoint", "provider": "custom",
             "model": "llama-3.1", "api_base_env": "CUSTOM_LLM_BASE_URL_1",
             "api_key_env": "CUSTOM_LLM_API_KEY_1", "is_dry_run": False},
        ]})
        out = str(tmp_path / "config.yaml")
        generate_litellm_config(src, out)

        cfg = self._load_yaml(out)
        params = cfg["model_list"][0]["litellm_params"]
        assert params["model"] == "openai/llama-3.1"
        assert params["api_base"] == "os.environ/CUSTOM_LLM_BASE_URL_1"
        assert params["api_key"] == "os.environ/CUSTOM_LLM_API_KEY_1"

    def test_ollama_provider_no_api_key(self, tmp_path):
        """Ollama provider produces api_base but no api_key."""
        src = write_yaml(tmp_path / "models.yaml", {"models": [
            {"id": "llama3.1", "name": "Ollama llama3.1", "provider": "ollama",
             "model": "llama3.1", "api_base_env": "OLLAMA_BASE_URL", "is_dry_run": False},
        ]})
        out = str(tmp_path / "config.yaml")
        generate_litellm_config(src, out)

        cfg = self._load_yaml(out)
        params = cfg["model_list"][0]["litellm_params"]
        assert params["model"] == "ollama/llama3.1"
        assert params["api_base"] == "os.environ/OLLAMA_BASE_URL"
        assert "api_key" not in params

    def test_dry_run_excluded(self, tmp_path):
        """Dry-run entries are not written to the LiteLLM config."""
        src = write_yaml(tmp_path / "models.yaml", {"models": [
            make_model("dr", "Dry Run", is_dry_run=True),
        ]})
        out = str(tmp_path / "config.yaml")
        generate_litellm_config(src, out)

        cfg = self._load_yaml(out)
        assert cfg["model_list"] == []

    def test_drop_params_always_set(self, tmp_path):
        """litellm_settings.drop_params is always True in generated config."""
        src = write_yaml(tmp_path / "models.yaml", {"models": []})
        out = str(tmp_path / "config.yaml")
        generate_litellm_config(src, out)

        cfg = self._load_yaml(out)
        assert cfg["litellm_settings"]["drop_params"] is True

    def test_output_file_created(self, tmp_path):
        """Output file is created even when parent dir doesn't exist yet."""
        src = write_yaml(tmp_path / "models.yaml", {"models": []})
        out = str(tmp_path / "subdir" / "config.yaml")
        generate_litellm_config(src, out)
        assert (tmp_path / "subdir" / "config.yaml").exists()


# ---------------------------------------------------------------------------
# Tests: generate_models_yaml
# ---------------------------------------------------------------------------

EXAMPLE_MODELS = [
    {"id": "claude-haiku-4-5", "name": "Claude Haiku", "provider": "anthropic",
     "model": "claude-haiku-4-5-20251001", "api_key_env": "ANTHROPIC_API_KEY", "is_dry_run": False},
    {"id": "gemini-3.5-flash", "name": "Gemini Flash", "provider": "google",
     "model": "gemini-3.5-flash", "api_key_env": "GEMINI_API_KEY", "is_dry_run": False},
    {"id": "gpt-4o", "name": "GPT-4o", "provider": "openai",
     "model": "gpt-4o", "api_key_env": "OPENAI_API_KEY", "is_dry_run": False},
    {"id": "o3-mini", "name": "o3-mini", "provider": "openai",
     "model": "o3-mini", "api_key_env": "OPENAI_API_KEY", "is_dry_run": False},
    {"id": "dry-run-dummy", "name": "Dry Run", "is_dry_run": True},
]


@pytest.fixture
def example_file(tmp_path):
    path = tmp_path / "models.example.yaml"
    path.write_text(yaml.dump({"models": EXAMPLE_MODELS}, default_flow_style=False))
    return str(path)


class TestGenerateModelsYaml:

    def _load(self, path):
        return yaml.safe_load(open(path).read())

    def test_single_provider_anthropic(self, example_file, tmp_path):
        """Only claude-* models (+ dry-run) returned for anthropic provider."""
        out = str(tmp_path / "models.yaml")
        generate_models_yaml(example_file, out, providers=["anthropic"])

        ids = [m["id"] for m in self._load(out)["models"]]
        assert "claude-haiku-4-5" in ids
        assert "gemini-3.5-flash" not in ids
        assert "gpt-4o" not in ids
        assert "dry-run-dummy" in ids

    def test_multiple_providers(self, example_file, tmp_path):
        """anthropic + google returns claude-* and gemini-* models."""
        out = str(tmp_path / "models.yaml")
        generate_models_yaml(example_file, out, providers=["anthropic", "google"])

        ids = [m["id"] for m in self._load(out)["models"]]
        assert "claude-haiku-4-5" in ids
        assert "gemini-3.5-flash" in ids
        assert "gpt-4o" not in ids
        assert "dry-run-dummy" in ids

    def test_openai_prefixes(self, example_file, tmp_path):
        """openai provider matches gpt-*, o3-*, o4-* prefixes."""
        out = str(tmp_path / "models.yaml")
        generate_models_yaml(example_file, out, providers=["openai"])

        ids = [m["id"] for m in self._load(out)["models"]]
        assert "gpt-4o" in ids
        assert "o3-mini" in ids
        assert "claude-haiku-4-5" not in ids

    def test_custom_endpoints_added(self, example_file, tmp_path):
        """Custom endpoint entries are appended with correct fields."""
        out = str(tmp_path / "models.yaml")
        generate_models_yaml(
            example_file, out, providers=["custom"],
            custom_entries=[{
                "id": "my-model",
                "name": "My Model",
                "remote_model": "llama-3.1",
                "api_base_env": "CUSTOM_LLM_BASE_URL_1",
                "api_key_env": "CUSTOM_LLM_API_KEY_1",
            }],
        )
        models = self._load(out)["models"]
        entry = next((m for m in models if m["id"] == "my-model"), None)
        assert entry is not None
        assert entry["name"] == "My Model"
        assert entry["provider"] == "custom"
        assert entry["model"] == "llama-3.1"
        assert any(m["id"] == "dry-run-dummy" for m in models)

    def test_ollama_models_added(self, example_file, tmp_path):
        """Ollama entries use em-dash format 'Ollama — <name>'."""
        out = str(tmp_path / "models.yaml")
        generate_models_yaml(
            example_file, out, providers=["ollama"],
            ollama_models=["llama3.1", "mistral"],
        )
        models = self._load(out)["models"]
        names = [m["name"] for m in models]
        assert "Ollama \u2014 llama3.1" in names
        assert "Ollama \u2014 mistral" in names
        assert any(m["id"] == "dry-run-dummy" for m in models)

    def test_dry_run_always_included(self, example_file, tmp_path):
        """Dry-run entry is always appended even if no provider matches."""
        out = str(tmp_path / "models.yaml")
        generate_models_yaml(example_file, out, providers=["nonexistent"])
        models = self._load(out)["models"]
        assert any(m.get("is_dry_run") for m in models)

    def test_no_providers_match(self, example_file, tmp_path):
        """No matching provider: only dry-run is returned."""
        out = str(tmp_path / "models.yaml")
        generate_models_yaml(example_file, out, providers=["nonexistent"])
        models = self._load(out)["models"]
        assert len(models) == 1
        assert models[0]["id"] == "dry-run-dummy"

    def test_output_file_written(self, example_file, tmp_path):
        """File is created at the output path."""
        out = str(tmp_path / "out" / "models.yaml")
        generate_models_yaml(example_file, out, providers=["anthropic"])
        assert (tmp_path / "out" / "models.yaml").exists()


# ---------------------------------------------------------------------------
# Tests: _BLOCKED_MODEL_PATTERNS / validate-model
# ---------------------------------------------------------------------------


class TestBlockedModelPatterns:

    @pytest.mark.parametrize("model", [
        "intfloat/e5-small-v2",
        "intfloat/e5-large-v2",
        "intfloat/multilingual-e5-base",
        "intfloat/multilingual-e5-large",
    ])
    def test_blocked_models_match_patterns(self, model):
        """All models in the unsupported families are caught by the blocklist."""
        matched = any(model.startswith(p) for p in _BLOCKED_MODEL_PATTERNS)
        assert matched, f"{model!r} should be blocked but was not matched"

    @pytest.mark.parametrize("model", [
        "BAAI/bge-base-en-v1.5",
        "sentence-transformers/all-mpnet-base-v2",
        "intfloat/e5",          # exact string without trailing dash — not blocked
    ])
    def test_compatible_models_not_blocked(self, model):
        """Models outside the blocked families are not rejected."""
        matched = any(model.startswith(p) for p in _BLOCKED_MODEL_PATTERNS)
        assert not matched, f"{model!r} should be allowed but was blocked"
