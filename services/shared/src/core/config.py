import os
import logging
from dataclasses import dataclass

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
    
    # --- RAG Thresholds ---
    # Defaults tuned for multilingual-e5-large
    TM_THRESHOLD: float = float(os.environ.get("TM_THRESHOLD", 0.23))
    GLOSSARY_THRESHOLD: float = float(os.environ.get("GLOSSARY_THRESHOLD", 0.25))
    RAG_STRICT_DISTANCE_THRESHOLD: float = float(os.environ.get("RAG_STRICT_DISTANCE_THRESHOLD", 0.08))

    # --- Paths ---
    PROMPTS_DIR: str = os.environ.get("PROMPTS_DIR", "/app/config/prompts")
    MODELS_CONFIG_PATH: str = os.environ.get("MODELS_CONFIG_PATH", "/app/config/models.json")
    TM_SOURCE_DIR: str = os.environ.get("TM_SOURCE_DIR", "/app/tm_source")
    
    # --- Embedding Model ---
    EMBEDDING_MODEL_NAME: str = "intfloat/multilingual-e5-large"
    
    # --- Localization ---
    TARGET_LANG: str = os.environ.get("TARGET_LANG", "ja")
    
    @classmethod
    def log_config(cls):
        """Logs critical configuration values for debugging."""
        logger.info(f"🔧 Config: CHROMA_HOST={cls.CHROMA_HOST}:{cls.CHROMA_PORT}")
        logger.info(f"🔧 Config: TM_THRESHOLD={cls.TM_THRESHOLD}, GLOSSARY_THRESHOLD={cls.GLOSSARY_THRESHOLD}")
        logger.info(f"🔧 Config: TARGET_LANG={cls.TARGET_LANG}")
