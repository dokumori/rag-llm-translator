import os
import json
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


def _require_env(var: str) -> str:
    """Returns the value of a required environment variable, raising EnvironmentError if unset or empty."""
    value = os.environ.get(var, "")
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{var}' is not set. "
            f"Ensure .env.defaults is loaded (e.g. via docker-compose env_file)."
        )
    return value


class Config:
    """Centralized configuration for the application."""

    # --- ChromaDB ---
    CHROMA_HOST: str = os.environ.get("CHROMA_HOST", "chroma")
    CHROMA_PORT: int = int(os.environ.get("CHROMA_PORT", 8000))
    TM_COLLECTION: str = os.environ.get("TM_COLLECTION", "app_tm")
    GLOSSARY_COLLECTION: str = os.environ.get("GLOSSARY_COLLECTION", "app_glossary")

    # --- LLM ---
    LLM_API_TOKEN: str = os.environ.get("LLM_API_TOKEN", "")
    LLM_BASE_URL: str = os.environ.get("LLM_BASE_URL", "")
    TM_THRESHOLD: float = float(os.environ.get("TM_THRESHOLD", 0.27))
    GLOSSARY_THRESHOLD: float = float(os.environ.get("GLOSSARY_THRESHOLD", 0.36))
    RAG_STRICT_DISTANCE_THRESHOLD: float = float(os.environ.get("RAG_STRICT_DISTANCE_THRESHOLD", 0.15))

    # --- Paths ---
    PROMPTS_DIR: str = os.environ.get("PROMPTS_DIR", "/app/config/prompts")
    MODELS_CONFIG_PATH: str = os.environ.get("MODELS_CONFIG_PATH", "/app/config/models/models.json")
    CUSTOM_MODELS_CONFIG_PATH: str = os.environ.get("CUSTOM_MODELS_CONFIG_PATH", "/app/config/models/custom/models.json")
    TM_SOURCE_DIR: str = os.environ.get("TM_SOURCE_DIR", "/app/tm_source")

    # --- Embedding ---
    # Changing this after data has been ingested will invalidate all vectors in ChromaDB.
    # If you change the model, you must reset and re-ingest all collections.
    EMBEDDING_MODEL_NAME: str = os.environ.get("EMBEDDING_MODEL_NAME", "")
    # The default model name, sourced from .env.defaults. Used to detect non-default model usage.
    DEFAULT_EMBEDDING_MODEL: str = _require_env("DEFAULT_EMBEDDING_MODEL")

    # --- Localisation ---
    # No default — target language must be provided explicitly per-request
    # (via URL path, CLI argument, etc.) to prevent cross-language contamination.
    TARGET_LANG: str = os.environ.get("TARGET_LANG", "")

    @classmethod
    def log_config(cls) -> None:
        """Logs critical configuration values for debugging."""
        logger.info(f"🔧 Config: CHROMA_HOST={cls.CHROMA_HOST}:{cls.CHROMA_PORT}")
        logger.info(f"🔧 Config: TM_THRESHOLD={cls.TM_THRESHOLD}, GLOSSARY_THRESHOLD={cls.GLOSSARY_THRESHOLD}")
        logger.info(f"🔧 Config: TARGET_LANG={cls.TARGET_LANG}")
        logger.info(f"🔧 Config: LLM_BASE_URL={cls.LLM_BASE_URL or '(not set — check .env)'}")


def load_models_config(models_path: str = None, custom_path: str = None) -> List[Dict[str, Any]]:
    """
    Loads model configurations with custom override support.

    Base models are loaded from `models_path` (defaults to Config.MODELS_CONFIG_PATH).
    If a custom `models.json` exists at `custom_path` (defaults to Config.CUSTOM_MODELS_CONFIG_PATH),
    its entries override base entries by matching `id`, and any new entries are appended.

    The custom file uses the same format as models.json:
      { "models": [ { "id": "...", "name": "...", ... }, ... ] }
    """
    if models_path is None:
        models_path = Config.MODELS_CONFIG_PATH
    if custom_path is None:
        custom_path = Config.CUSTOM_MODELS_CONFIG_PATH

    # Load base models
    base_models: List[Dict[str, Any]] = []
    if os.path.exists(models_path):
        try:
            with open(models_path, "r", encoding="utf-8") as f:
                base_models = json.load(f).get("models", [])
        except Exception as e:
            logger.error(f"❌ Failed to load base models config from {models_path}: {e}")
    else:
        logger.warning(f"⚠️ Models config file not found at: {models_path}")

    # Custom override strategy: when custom/models.json exists it
    # REPLACES the base model list entirely — not merges with it.  Only the single
    # dry-run sentinel from the base file is carried over so that test/dry-run mode
    # always works regardless of what the custom file contains.
    #
    # Practical implication: any model you want available at runtime must be listed
    # in custom/models.json when that file exists.  Adding a model only to the base
    # models.json has no effect while a custom file is present.
    if os.path.exists(custom_path):
        try:
            with open(custom_path, "r", encoding="utf-8") as f:
                custom_models = json.load(f).get("models", [])
            custom_ids = {m["id"] for m in custom_models if "id" in m}

            dry_run = next((m for m in base_models if m.get("is_dry_run")), None)

            final_models = list(custom_models)
            if dry_run and dry_run.get("id") not in custom_ids:
                final_models.append(dry_run)

            logger.info(f"📋 Loaded {len(custom_models)} custom models and {'one' if dry_run else 'zero'} default dry-run model")
            _validate_model_flags(final_models)
            return final_models

        except Exception as e:
            logger.error(f"❌ Failed to load custom models config from {custom_path}: {e}")

    _validate_model_flags(base_models)
    return base_models


# Note: omit_temperature and use_max_completion_tokens were removed in v5.0.0.
# LiteLLM normalises provider-specific parameter differences (temperature,
# max_tokens vs max_completion_tokens) transparently, so these flags are no
# longer needed in direct app code.
_BOOLEAN_FLAGS = ("is_dry_run",)


def _validate_model_flags(models: List[Dict[str, Any]]) -> None:
    """Warns when model flag fields contain non-boolean values (e.g. the string "false")."""
    for model in models:
        for flag in _BOOLEAN_FLAGS:
            value = model.get(flag)
            if value is not None and not isinstance(value, bool):
                logger.warning(
                    f"⚠️ Model '{model.get('id', '?')}': flag '{flag}' should be "
                    f"a boolean (true/false), got {type(value).__name__}: {value!r}"
                )
