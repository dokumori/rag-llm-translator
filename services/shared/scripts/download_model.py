
import os
import logging
from sentence_transformers import SentenceTransformer

# Simple logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("download_model")

def download():
    # Fetch from env var, matching the ARG in Dockerfile
    # Default matching our config default
    model_name = os.environ.get("EMBEDDING_MODEL_NAME", "intfloat/multilingual-e5-large")
    logger.info(f"💾 Pre-downloading model: {model_name}...")
    
    # This triggers the download to HF_HOME
    SentenceTransformer(model_name)
    
    logger.info("✅ Model download complete.")

if __name__ == "__main__":
    download()
