import logging
import os
import threading
from typing import Optional

import chromadb
from chromadb.utils import embedding_functions

from core.config import Config

logger = logging.getLogger(__name__)

# Models known to require query:/passage: prefixes — incompatible with this application.
# See docs/7_embedding_model.md for model requirements.
_BLOCKED_MODEL_PATTERNS = [
    "intfloat/e5-",
    "intfloat/multilingual-e5-",
]

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
                model_name = Config.EMBEDDING_MODEL_NAME

                # --- Blocklist check ---
                # Block models known to require query:/passage: prefixes, which this
                # application does not support (would require changes to ingestion +
                # query code throughout).
                for pattern in _BLOCKED_MODEL_PATTERNS:
                    if model_name.startswith(pattern):
                        raise ValueError(
                            f"❌ Embedding model '{model_name}' requires query/passage prefixes "
                            f"which are not supported by this application.\n"
                            f"See docs/7_embedding_model.md for compatible model requirements."
                        )

                # --- Model cache check ---
                # With the two-step build, models live in the bind-mounted host directory.
                # Fail fast with a clear message if the user forgot to run download-model.sh.
                # We check for `models--*` directories inside `hub/` — the layout Hugging Face
                # uses for downloaded models — rather than checking hf_home itself, which may
                # contain non-model artefacts like .gitkeep, CACHEDIR.TAG, or lock files.
                hf_home = os.environ.get("HF_HOME", "/app/data/cache/huggingface")
                hub_dir = os.path.join(hf_home, "hub")
                has_models = os.path.isdir(hub_dir) and any(
                    f.startswith("models--") for f in os.listdir(hub_dir)
                )
                if not has_models:
                    raise RuntimeError(
                        f"❌ Model cache is empty at '{hf_home}'.\n"
                        f"Run 'bin/download-model.sh' to download the embedding model first.\n"
                        f"If you changed EMBEDDING_MODEL_NAME, run "
                        f"'bin/download-model.sh {model_name}'."
                    )

                logger.info(f"⏳ Loading Embedding Model ({model_name})...")
                try:
                    import warnings
                    # Suppress a known-benign warning from transformers when loading BGE models:
                    # 'embeddings.position_ids' appears as UNEXPECTED in the load report because
                    # the architecture computes position IDs dynamically and doesn't load this weight.
                    # This does not affect embedding quality or correctness.
                    with warnings.catch_warnings():
                        warnings.filterwarnings("ignore", message=".*position_ids.*")
                        _embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                            model_name=model_name
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
