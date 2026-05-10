
import os
import logging

# Set root logger to WARNING before importing sentence_transformers/transformers
# so their internal INFO/DEBUG chatter is suppressed.
logging.basicConfig(level=logging.WARNING)

# Silence specific chatty libraries that log at INFO even with the root set above,
# because some of them call basicConfig themselves or use their own handlers.
for lib in ("sentence_transformers", "transformers", "huggingface_hub", "torch", "filelock"):
    logging.getLogger(lib).setLevel(logging.ERROR)

logger = logging.getLogger("download_model")
logger.setLevel(logging.INFO)

# Attach a plain handler so our own messages still appear without a log-level prefix.
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(_handler)
logger.propagate = False


def download():
    model_name = os.environ.get("EMBEDDING_MODEL_NAME", "")
    logger.info(f"💾 Downloading model: {model_name}...")

    from sentence_transformers import SentenceTransformer
    SentenceTransformer(model_name)

    logger.info("✅ Model download complete.")


if __name__ == "__main__":
    download()
