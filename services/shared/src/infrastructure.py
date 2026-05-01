import logging
import threading
from typing import Optional

import chromadb
from chromadb.utils import embedding_functions

from core.config import Config

logger = logging.getLogger(__name__)

# Module-level singletons and their guards
_embedding_fn: Optional[embedding_functions.SentenceTransformerEmbeddingFunction] = None
_chroma_client: Optional[chromadb.HttpClient] = None
_embedding_lock = threading.Lock()
_chroma_lock = threading.Lock()


def get_embedding_function() -> embedding_functions.SentenceTransformerEmbeddingFunction:
    """Returns the singleton embedding function, initialised at most once (thread-safe)."""
    global _embedding_fn
    if _embedding_fn is None:
        with _embedding_lock:
            if _embedding_fn is None:  # double-checked locking
                logger.info(f"⏳ Loading Embedding Model ({Config.EMBEDDING_MODEL_NAME})...")
                try:
                    import warnings
                    # Suppress a known-benign warning from transformers when loading BGE models:
                    # 'embeddings.position_ids' appears as UNEXPECTED in the load report because
                    # the architecture computes position IDs dynamically and doesn't load this weight.
                    # This does not affect embedding quality or correctness.
                    with warnings.catch_warnings():
                        warnings.filterwarnings("ignore", message=".*position_ids.*")
                        _embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                            model_name=Config.EMBEDDING_MODEL_NAME
                        )
                    logger.info("✅ Embedding Model Loaded.")
                except Exception as e:
                    logger.error(f"❌ Failed to load embedding model: {e}")
                    raise e
    return _embedding_fn


def get_chroma_client() -> chromadb.HttpClient:
    """Returns the singleton ChromaDB client, initialised at most once (thread-safe)."""
    global _chroma_client
    if _chroma_client is None:
        with _chroma_lock:
            if _chroma_client is None:  # double-checked locking
                logger.info(f"🔌 Connecting to ChromaDB at {Config.CHROMA_HOST}:{Config.CHROMA_PORT}...")
                try:
                    _chroma_client = chromadb.HttpClient(
                        host=Config.CHROMA_HOST,
                        port=Config.CHROMA_PORT
                    )
                except Exception as e:
                    logger.error(f"❌ Failed to connect to ChromaDB: {e}")
                    raise e
    return _chroma_client
