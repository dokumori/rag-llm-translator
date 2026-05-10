#!/bin/bash
# bin/download-model.sh
#
# Downloads an embedding model into data/cache/huggingface/ on the host.
# The download runs inside the rag-proxy container (which has sentence-transformers
# installed) with HF_HUB_OFFLINE=0 temporarily disabled.
#
# Usage:
#   bin/download-model.sh                          # uses EMBEDDING_MODEL_NAME from .env
#   bin/download-model.sh BAAI/bge-base-en-v1.5    # downloads specific model
#   bin/download-model.sh BAAI/bge-base-en-v1.5 -y # skip all prompts (use cache if present)
#
# Prerequisites: docker compose build must have been run first.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

source "$SCRIPT_DIR/common.sh"
cd "$PROJECT_ROOT"
load_env

# Parse arguments — model name (positional) and optional -y flag.
MODEL=""
AUTO_YES=false
for arg in "$@"; do
    case "$arg" in
        -y) AUTO_YES=true ;;
        -*) echo "❌ Unknown flag: $arg"; exit 1 ;;
        *)
            if [ -z "$MODEL" ]; then
                MODEL="$arg"
            else
                echo "❌ Unexpected argument: $arg"
                exit 1
            fi
            ;;
    esac
done
MODEL="${MODEL:-$EMBEDDING_MODEL_NAME}"
CACHE_DIR="${PROJECT_ROOT}/data/cache/huggingface"

# --- Blocklist check (mirrors infrastructure.py) ---
# Fail early on the host side before spinning up the container.
for pattern in "intfloat/e5-" "intfloat/multilingual-e5-"; do
    if [[ "$MODEL" == "$pattern"* ]]; then
        echo ""
        echo "❌ Unsupported model: '$MODEL'"
        echo "   Models in the 'intfloat/e5-*' and 'intfloat/multilingual-e5-*' families"
        echo "   require query:/passage: prefixes which are not supported by this application."
        echo "   See docs/7_embedding_model.md for compatible model requirements."
        exit 1
    fi
done

echo ""
echo "===================================================================="
echo " 💾 Embedding Model Download"
echo "===================================================================="
echo "   Model     : $MODEL"
echo "   Cache dir : $CACHE_DIR"
echo ""

mkdir -p "$CACHE_DIR"

# ---------------------------------------------------------------------------
# Cache detection
# HuggingFace hub stores models under:
#   hub/models--<ORG>--<NAME>/snapshots/<commit-hash>/
# Derive the folder name by replacing '/' with '--' and prepending 'models--'.
# A model is considered cached if that snapshots/ directory is non-empty.
# ---------------------------------------------------------------------------
MODEL_CACHE_KEY="models--$(echo "$MODEL" | sed 's|/|--|g')"
SNAPSHOTS_DIR="${CACHE_DIR}/hub/${MODEL_CACHE_KEY}/snapshots"

if [ -d "$SNAPSHOTS_DIR" ] && [ -n "$(ls -A "$SNAPSHOTS_DIR" 2>/dev/null)" ]; then
    CACHED_SNAPSHOT=$(ls -1 "$SNAPSHOTS_DIR" | head -1)
    CACHED_SIZE=$(du -sh "${SNAPSHOTS_DIR}/${CACHED_SNAPSHOT}" 2>/dev/null | cut -f1 || echo "unknown")
    echo "✅ Model already cached!"
    echo "   Snapshot : $CACHED_SNAPSHOT"
    echo "   Size     : $CACHED_SIZE"
    echo ""

    if [ "$AUTO_YES" = true ]; then
        echo "(-y flag set — using existing cache, skipping download)"
        echo ""
        echo "✅ Using cached model '$MODEL'."
        echo ""
        echo "If you switched models, restart rag-proxy and toolbox to pick up the change:"
        echo "  docker compose up -d --force-recreate rag-proxy toolbox"
        exit 0
    fi

    read -rp "Use existing cache? [Y/n]: " use_cache
    if [[ -z "$use_cache" || "$use_cache" =~ ^[Yy]$ ]]; then
        echo ""
        echo "✅ Using cached model '$MODEL'. No download needed."
        echo ""
        echo "If you switched models, restart rag-proxy and toolbox to pick up the change:"
        echo "  docker compose up -d --force-recreate rag-proxy toolbox"
        exit 0
    fi
    echo ""
    echo "⬇️  Proceeding with fresh download (will overwrite cache)..."
fi

echo "⏳ Starting download (this may take several minutes for large models)..."

# Pre-flight: verify the image has the download script.
# If the old image (pre-refactor) is still in use, download_model.py was deleted
# during the build and won't exist. A rebuild is required.
# --no-deps skips starting the chroma dependency — we only need the image itself.
if ! docker compose run --no-deps --rm \
    -e HF_HUB_OFFLINE=0 \
    -e TORCH_COMPILE_DISABLE=1 \
    -e TORCHINDUCTOR_CACHE_DIR=/tmp/torchinductor \
    rag-proxy \
    test -f /app/download_model.py 2>/dev/null; then
    echo ""
    echo "❌ /app/download_model.py not found in the rag-proxy image."
    echo "   The image needs to be rebuilt before the model can be downloaded."
    echo ""
    echo "   Run: docker compose build rag-proxy"
    echo "   Then retry: bin/download-model.sh"
    exit 1
fi

# --no-deps: the download script only needs the Python environment inside rag-proxy,
# not a running ChromaDB instance.
docker compose run --no-deps --rm --quiet-pull \
    -e HF_HUB_OFFLINE=0 \
    -e TORCH_COMPILE_DISABLE=1 \
    -e TORCHINDUCTOR_CACHE_DIR=/tmp/torchinductor \
    -e TRANSFORMERS_VERBOSITY=error \
    -e TOKENIZERS_PARALLELISM=false \
    -e EMBEDDING_MODEL_NAME="$MODEL" \
    -v "${CACHE_DIR}:/app/data/cache/huggingface" \
    rag-proxy \
    python /app/download_model.py

echo ""
echo "✅ Model '$MODEL' downloaded to data/cache/huggingface/"
echo ""
echo "If you switched models, restart rag-proxy and toolbox to pick up the change:"
echo "  docker compose up -d --force-recreate rag-proxy toolbox"
