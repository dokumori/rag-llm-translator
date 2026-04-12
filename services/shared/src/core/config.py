import os
import json
import logging
from dataclasses import dataclass
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

@dataclass
class Config:
    """Centralized configuration for the application."""
    
    # --- ChromaDB Configuration ---
    CHROMA_HOST: str = os.environ.get("CHROMA_HOST", "chroma")
    CHROMA_PORT: int = int(os.environ.get("CHROMA_PORT", 8000))
    
    # Collections
    TM_COLLECTION: str = os.environ.get("TM_COLLECTION", "app_tm")
    GLOSSARY_COLLECTION: str = os.environ.get("GLOSSARY_COLLECTION", "app_glossary")

    # --- LLM Configuration ---
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
    
    # --- Embedding Model ---
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-large-en-v1.5"
    
    # --- Localization ---
    TARGET_LANG: str = os.environ.get("TARGET_LANG", "ja")
    
    @classmethod
    def log_config(cls):
        """Logs critical configuration values for debugging."""
        logger.info(f"🔧 Config: CHROMA_HOST={cls.CHROMA_HOST}:{cls.CHROMA_PORT}")
        logger.info(f"🔧 Config: TM_THRESHOLD={cls.TM_THRESHOLD}, GLOSSARY_THRESHOLD={cls.GLOSSARY_THRESHOLD}")
        logger.info(f"🔧 Config: TARGET_LANG={cls.TARGET_LANG}")


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

    # 1. Load base models
    base_models: List[Dict[str, Any]] = []
    if os.path.exists(models_path):
        try:
            with open(models_path, "r", encoding="utf-8") as f:
                base_models = json.load(f).get("models", [])
        except Exception as e:
            logger.error(f"❌ Failed to load base models config from {models_path}: {e}")
    else:
        logger.warning(f"⚠️ Models config file not found at: {models_path}")

    # 2. Merge custom overrides (if file exists)
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
            return final_models

        except Exception as e:
            logger.error(f"❌ Failed to load custom models config from {custom_path}: {e}")

    return base_models
