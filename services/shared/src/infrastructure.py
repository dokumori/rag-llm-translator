
import logging
from typing import Optional
import chromadb
from chromadb.utils import embedding_functions
from core.config import Config

logger = logging.getLogger(__name__)

# Singletons (Lazy Loading)
_e5_ef: Optional[embedding_functions.SentenceTransformerEmbeddingFunction] = None
_chroma_client: Optional[chromadb.HttpClient] = None


def get_embedding_function() -> embedding_functions.SentenceTransformerEmbeddingFunction:
    """
    Returns the singleton instance of the embedding function.
    Loads it strictly once.
    """
    global _e5_ef
    if _e5_ef is None:
        logger.info(f"⏳ Loading Embedding Model ({Config.EMBEDDING_MODEL_NAME})...")
        try:
            _e5_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=Config.EMBEDDING_MODEL_NAME
            )
            logger.info("✅ Embedding Model Loaded.")
        except Exception as e:
            logger.error(f"❌ Failed to load embedding model: {e}")
            raise e
    return _e5_ef


def get_chroma_client() -> chromadb.HttpClient:
    """
    Returns the singleton instance of the ChromaDB client.
    """
    global _chroma_client
    if _chroma_client is None:
        logger.info(f"🔌 Connecting to ChromaDB at {Config.CHROMA_HOST}:{Config.CHROMA_PORT}...")
        try:
            _chroma_client = chromadb.HttpClient(
                host=Config.CHROMA_HOST,
                port=Config.CHROMA_PORT
            )
            # Optional: Test header or heartbeat here if desired,
            # currently we trust the client init.
        except Exception as e:
            logger.error(f"❌ Failed to connect to ChromaDB: {e}")
            raise e
    return _chroma_client
