#!/bin/bash
# bin/switch-embedding-model.sh
#
# Safely switches the text embedding model used by the RAG pipeline.
#
# This script:
#   1. Validates the new model against the blocklist
#   2. Asks for confirmation (or proceeds with -y)
#   3. Backs up the current ChromaDB state
#   4. Deletes all ChromaDB collections directly (bypassing rag-proxy,
#      so they are not re-created with the old model's metadata)
#   5. Updates EMBEDDING_MODEL_NAME and resets thresholds in .env
#   6. Downloads the new model into data/cache/huggingface/
#   7. Restarts rag-proxy to pick up the new model
#
# Usage:
#   bin/switch-embedding-model.sh <model-name>
#   bin/switch-embedding-model.sh <model-name> -y   # skip confirmations
#
# After switching:
#   1. bin/ingest.sh        — re-ingest all your data
#   2. Follow docs/3_RAG_performance_analysis.md to recalibrate thresholds

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

source "$SCRIPT_DIR/common.sh"
cd "$PROJECT_ROOT"
load_env

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------

NEW_MODEL=""
AUTO_YES=false

for arg in "$@"; do
    case "$arg" in
        -y) AUTO_YES=true ;;
        -*) echo "❌ Unknown flag: $arg"; exit 1 ;;
        *)
            if [ -z "$NEW_MODEL" ]; then
                NEW_MODEL="$arg"
            else
                echo "❌ Unexpected argument: $arg"
                exit 1
            fi
            ;;
    esac
done

if [ -z "$NEW_MODEL" ]; then
    echo "Usage: bin/switch-embedding-model.sh <new-model-name> [-y]"
    echo ""
    echo "Examples:"
    echo "  bin/switch-embedding-model.sh BAAI/bge-base-en-v1.5"
    echo "  bin/switch-embedding-model.sh sentence-transformers/all-mpnet-base-v2 -y"
    echo ""
    echo "See docs/7_embedding_model.md for compatible models."
    exit 1
fi

CURRENT_MODEL="$EMBEDDING_MODEL_NAME"

# ---------------------------------------------------------------------------
# Step 1: Blocklist check
# ---------------------------------------------------------------------------

for pattern in "intfloat/e5-" "intfloat/multilingual-e5-"; do
    if [[ "$NEW_MODEL" == "$pattern"* ]]; then
        echo ""
        echo "❌ Unsupported model: '$NEW_MODEL'"
        echo "   Models in the 'intfloat/e5-*' and 'intfloat/multilingual-e5-*' families"
        echo "   require query:/passage: prefixes which are not supported by this application."
        echo "   See docs/7_embedding_model.md for compatible model requirements."
        exit 1
    fi
done

if [ "$NEW_MODEL" = "$CURRENT_MODEL" ]; then
    # .env already matches — but check if ChromaDB collections are also consistent.
    # If a previous switch was interrupted after .env was updated but before
    # collections were wiped, the model in .env and the model stored in collection
    # metadata will disagree.  In that case we must NOT exit early.
    echo "ℹ️  '$NEW_MODEL' is already set in .env. Checking ChromaDB for stale collections..."

    MISMATCH_RESULT=$(docker compose run --no-deps --rm \
        -e CHROMA_HOST=chroma \
        -e CHROMA_PORT=8000 \
        -e TARGET_MODEL="$NEW_MODEL" \
        rag-proxy \
        python3 /app/check_collection_model.py 2>/dev/null || echo "ERROR")

    if [[ "$MISMATCH_RESULT" == "OK" ]]; then
        echo "ℹ️  Collections are consistent with '$NEW_MODEL'. Nothing to do."
        exit 0
    elif [[ "$MISMATCH_RESULT" == ERROR* ]]; then
        echo "⚠️  Could not reach ChromaDB to verify collection state."
        echo "   If rag-proxy is stuck in a mismatch loop, run:"
        echo "     docker compose up chroma -d"
        echo "   and retry this script."
        exit 1
    else
        # Stale collections found — fall through to the full switch procedure
        STALE_INFO=$(echo "$MISMATCH_RESULT" | grep '^MISMATCH:' | head -1 | cut -d: -f2-)
        echo "⚠️  Stale collections detected (ingested with: $STALE_INFO)."
        echo "   Proceeding with collection wipe to restore consistency..."
        echo ""
    fi
fi

# ---------------------------------------------------------------------------
# Step 2: Confirmation
# ---------------------------------------------------------------------------

echo ""
echo "===================================================================="
echo " 🔄 Embedding Model Switch"
echo "===================================================================="
echo "   Current model : $CURRENT_MODEL"
echo "   New model     : $NEW_MODEL"
echo ""
echo "This will:"
echo "  1. Back up the current ChromaDB collections"
echo "  2. Delete ALL ChromaDB collections (TM + Glossary)"
echo "  3. Update EMBEDDING_MODEL_NAME in .env"
echo "  4. Reset thresholds to permissive defaults (recalibration required)"
echo "  5. Download the new model (~1-2GB)"
echo "  6. Restart rag-proxy"
echo ""
echo "⚠️  You will need to re-ingest all your TM and Glossary data afterwards."
echo ""

if [ "$AUTO_YES" = true ]; then
    echo "(-y flag set — proceeding without confirmation)"
else
    read -rp "Proceed? [y/N]: " confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        echo "❌ Switch cancelled."
        exit 0
    fi
fi

# ---------------------------------------------------------------------------
# Step 3/7: Backup
# (1/5 for the users)
# ---------------------------------------------------------------------------

echo ""
echo "===================================================================="
echo " 📦 Step 1/5: Backing up ChromaDB..."
echo "===================================================================="
bash "$SCRIPT_DIR/manage-backup.sh" --dump -y

# ---------------------------------------------------------------------------
# Step 4/7: Delete ChromaDB collections directly via a disposable rag-proxy
#           container (--no-deps --rm), bypassing toolbox entirely.
#
# WHY before .env update:
#   If deletion fails, .env has NOT been touched yet — the system stays in a
#   fully consistent state (old model in .env + old model in ChromaDB) and
#   the user can simply retry.  Updating .env first and then failing leaves an
#   irrecoverable mismatch that blocks rag-proxy from starting.
#
# WHY --no-deps --rm (not 'exec toolbox'):
#   toolbox has a depends_on: rag-proxy: service_healthy condition.
#   If rag-proxy is unhealthy (e.g. a previous failed switch), toolbox will
#   not be running and 'docker compose exec toolbox' will fail.  Using a
#   disposable rag-proxy container sidesteps that dependency entirely —
#   rag-proxy has chromadb installed and can reach chroma on app_network.
# ---------------------------------------------------------------------------

echo ""
echo "===================================================================="
echo " 🗑️  Step 2/5: Deleting ChromaDB collections..."
echo "===================================================================="

# Run inside a disposable rag-proxy container that is already on app_network
# and has chromadb installed.  CHROMA_HOST/PORT come from the service env.
docker compose run --no-deps --rm \
    -e CHROMA_HOST=chroma \
    -e CHROMA_PORT=8000 \
    rag-proxy \
    python3 /app/delete_collections.py

# Verify deletion actually took effect — ChromaDB should now be empty.
# If collections survived (e.g. due to a ChromaDB write-ahead log or a silent
# failure), rag-proxy would start into a mismatch state. Catch it here instead.
echo "🔍 Verifying collections are gone..."
REMAINING=$(docker compose run --no-deps --rm \
    -e CHROMA_HOST=chroma \
    -e CHROMA_PORT=8000 \
    rag-proxy \
    python3 -c "
import chromadb, os, sys
c = chromadb.HttpClient(host=os.environ.get('CHROMA_HOST','chroma'), port=int(os.environ.get('CHROMA_PORT',8000)))
cols = c.list_collections()
if cols:
    for col in cols:
        print(col.name)
    sys.exit(1)
" 2>/dev/null && echo "OK" || echo "REMAINING")

if [[ "$REMAINING" != "OK" ]]; then
    echo ""
    echo "❌ Collections still exist in ChromaDB after deletion attempt."
    echo "   This is unexpected — ChromaDB may not have flushed the delete to disk."
    echo ""
    echo "   Remaining: $REMAINING"
    echo ""
    echo "   Try stopping ChromaDB fully and retrying:"
    echo "     docker compose stop chroma && docker compose up -d chroma"
    echo "     bin/switch-embedding-model.sh $NEW_MODEL"
    exit 1
fi
echo "   ✅ ChromaDB is empty — safe to proceed."

# ---------------------------------------------------------------------------
# Step 5/7: Update .env (model + thresholds)
#
# Collections are now gone, so updating .env is safe: even if a subsequent
# step fails, rag-proxy will start cleanly (no collections → no mismatch).
#
# A trap restores the original .env value if anything from this point on
# fails, so the user doesn't end up with a mismatched .env after a partial
# run (e.g. model download interrupted).
# ---------------------------------------------------------------------------

echo ""
echo "===================================================================="
echo " ✏️  Step 3/5: Updating .env..."
echo "===================================================================="

ENV_FILE="${PROJECT_ROOT}/.env"

# NOTE: No rollback trap.
# Collections are already gone at this point. Rolling .env back to the old model
# would create an *inverted* mismatch (old model in .env, new vectors in ChromaDB)
# which is just as broken as the original problem.
#
# If the download step fails after this point, re-running this script will NOT resume
# the download (because ChromaDB is empty and .env matches). To recover, you must:
#   1. bin/download-model.sh <new-model>
#   2. docker compose up -d --force-recreate rag-proxy

# Update EMBEDDING_MODEL_NAME (macOS-compatible: sed via temp file)
TEMP_FILE=$(mktemp)
sed "s|^EMBEDDING_MODEL_NAME=.*|EMBEDDING_MODEL_NAME=${NEW_MODEL}|" "$ENV_FILE" > "$TEMP_FILE"
mv "$TEMP_FILE" "$ENV_FILE"

# Reset thresholds to permissive defaults.
# These defaults prevent the new model from silently discarding all matches
# until the thresholds have been properly recalibrated.
TEMP_FILE=$(mktemp)
sed \
    -e 's|^TM_THRESHOLD=.*|TM_THRESHOLD=0.4|' \
    -e 's|^GLOSSARY_THRESHOLD=.*|GLOSSARY_THRESHOLD=0.4|' \
    -e 's|^RAG_STRICT_DISTANCE_THRESHOLD=.*|RAG_STRICT_DISTANCE_THRESHOLD=0.15|' \
    "$ENV_FILE" > "$TEMP_FILE"
mv "$TEMP_FILE" "$ENV_FILE"

echo "   EMBEDDING_MODEL_NAME          → $NEW_MODEL"
echo "   TM_THRESHOLD                  → 0.4  (permissive default, recalibration required)"
echo "   GLOSSARY_THRESHOLD            → 0.4  (permissive default, recalibration required)"
echo "   RAG_STRICT_DISTANCE_THRESHOLD → 0.15 (default, recalibration required)"
echo ""
echo "   ⚠️  Thresholds set to 0.4 are permissive defaults, and not calibrated for the new model."
echo "      See docs/3_RAG_performance_analysis.md before using in production."

# Critical: Re-export the updated values into the shell environment.
# load_env at the top of this script exported the OLD EMBEDDING_MODEL_NAME.
# Docker Compose resolves ${VAR} from the shell environment with HIGHER
# priority than the .env file on disk.  Without this re-export, the
# 'docker compose up' in step 5 would start rag-proxy with the OLD model,
# causing a silent metadata mismatch in newly-ingested collections.
export EMBEDDING_MODEL_NAME="$NEW_MODEL"
export TM_THRESHOLD=0.4
export GLOSSARY_THRESHOLD=0.4
export RAG_STRICT_DISTANCE_THRESHOLD=0.15

# ---------------------------------------------------------------------------
# Step 6/7: Download new model
# ---------------------------------------------------------------------------

echo ""
echo "===================================================================="
echo " 💾 Step 4/5: Downloading new model..."
echo "===================================================================="
if ! bash "$SCRIPT_DIR/download-model.sh" "$NEW_MODEL" -y; then
    echo ""
    echo "❌ ERROR: Model download failed!"
    echo "   The system is in a partial state: ChromaDB has been wiped and .env"
    echo "   is updated, but the new model files are missing."
    echo ""
    echo "   Re-running this switch script will NOT resume the download."
    echo "   To fully recover and finish the process, you must manually run:"
    echo ""
    echo "     bin/download-model.sh $NEW_MODEL"
    echo "     docker compose up -d --force-recreate rag-proxy"
    echo ""
    exit 1
fi

# All steps succeeded.

# ---------------------------------------------------------------------------
# Step 7/7: Restart rag-proxy to pick up new EMBEDDING_MODEL_NAME from .env
# ---------------------------------------------------------------------------

echo ""
echo "===================================================================="
echo " 🔄 Step 5/5: Restarting rag-proxy..."
echo "===================================================================="

# The backup step paused and unpaused ChromaDB, which resets its health status
# back to 'starting'. docker compose up --force-recreate rag-proxy has
# depends_on: chroma: condition: service_healthy, so it will fail if chroma
# hasn't re-passed its healthcheck yet (start_period=10s + interval=10s = up to 20s).
# Wait here before attempting the restart.
echo -n "⏳ Waiting for ChromaDB to become healthy"
chroma_timeout=30
chroma_elapsed=0
CHROMA_STATUS="starting"
while [ $chroma_elapsed -lt $chroma_timeout ]; do
    CHROMA_STATUS=$(docker inspect --format='{{.State.Health.Status}}' chroma 2>/dev/null || echo "error")
    if [ "$CHROMA_STATUS" = "healthy" ]; then
        break
    fi
    echo -n "."
    sleep 2
    chroma_elapsed=$((chroma_elapsed + 2))
done
echo ""

if [ "$CHROMA_STATUS" != "healthy" ]; then
    echo ""
    echo "❌ ChromaDB did not become healthy within ${chroma_timeout}s (status: ${CHROMA_STATUS})."
    echo "   The model switch is almost complete — .env and model files are ready,"
    echo "   but rag-proxy has not been restarted yet."
    echo ""
    echo "   To recover:"
    echo "     1. Fix ChromaDB:  docker compose up -d chroma"
    echo "     2. Restart proxy: docker compose up -d --force-recreate rag-proxy"
    echo ""
    echo "   Check logs: docker compose logs chroma --tail=20"
    exit 1
fi
echo "   ✅ ChromaDB is healthy."
echo ""

if ! docker compose up -d --force-recreate rag-proxy; then
    echo ""
    echo "❌ Failed to recreate rag-proxy container."
    echo "   The model switch is almost complete — .env and model files are ready."
    echo ""
    echo "   To recover, restart rag-proxy manually:"
    echo "     docker compose up -d --force-recreate rag-proxy"
    exit 1
fi

echo ""
echo -n "⏳ Waiting for rag-proxy to become healthy"

# 90s gives the healthcheck time to pass: start_period=30s + up to one interval=30s + check.
# When healthy, this loop exits on the first passing check (~5–10s after start).
timeout=90
elapsed=0
STATUS="starting"
while [ $elapsed -lt $timeout ]; do
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' rag-proxy 2>/dev/null || echo "error")
    if [ "$STATUS" = "healthy" ]; then
        break
    fi
    echo -n "."
    sleep 2
    elapsed=$((elapsed + 2))
done

echo ""

if [ "$STATUS" != "healthy" ]; then
    echo ""
    echo "❌ rag-proxy failed to become healthy within $timeout seconds (status: $STATUS)."
    echo "   The model switch is complete (.env and model files are ready), but"
    echo "   rag-proxy is not serving traffic yet."
    echo ""
    echo "   Check logs:  docker compose logs rag-proxy --tail=30"
    echo "   To retry:    docker compose up -d --force-recreate rag-proxy"
    exit 1
fi

# ---------------------------------------------------------------------------
# Post-switch verification
# Confirm that the running rag-proxy container actually loaded the new model.
# This catches the exact bug where Docker Compose silently used a stale shell
# variable (from the old load_env) instead of the updated .env value.
# ---------------------------------------------------------------------------

LIVE_MODEL=$(docker exec rag-proxy printenv EMBEDDING_MODEL_NAME 2>/dev/null || echo "")

if [ "$LIVE_MODEL" != "$NEW_MODEL" ]; then
    echo ""
    echo "❌ VERIFICATION FAILED: rag-proxy is running with the wrong model!"
    echo "   Expected : $NEW_MODEL"
    echo "   Actual   : ${LIVE_MODEL:-<not set>}"
    echo ""
    echo "   This is the exact stale-environment bug. To fix:"
    echo "     docker compose up -d --force-recreate rag-proxy toolbox"
    exit 1
fi

# ---------------------------------------------------------------------------
# Restart toolbox so it picks up the new EMBEDDING_MODEL_NAME.
# toolbox depends on rag-proxy: service_healthy, so rag-proxy must be healthy
# (confirmed above) before we recreate it.  Without this step, check_db.py
# would still report the old model name from the stale container environment.
# ---------------------------------------------------------------------------

echo ""
echo "===================================================================="
echo " 🔄 Restarting toolbox..."
echo "===================================================================="

if ! docker compose up -d --force-recreate toolbox; then
    echo ""
    echo "⚠️  WARNING: Failed to recreate toolbox container."
    echo "   rag-proxy is running correctly with '$NEW_MODEL',"
    echo "   but toolbox still has the old model in its environment."
    echo "   check_db.py may report a false mismatch until you run:"
    echo "     docker compose up -d --force-recreate toolbox"
fi

echo ""
echo "===================================================================="
echo " ✅ Model switch complete!"
echo "===================================================================="
echo ""
echo "New model  : $NEW_MODEL"
echo "Old model  : $CURRENT_MODEL"
echo ""
echo "✅ Verified: rag-proxy is running with '$NEW_MODEL'."
echo ""
echo "⚠️  ChromaDB is now empty. Next steps:"
echo ""
echo "  1. Re-ingest your data:"
echo "     bin/ingest.sh"
echo ""
echo "  2. Recalibrate RAG thresholds for the new model:"
echo "     See docs/3_RAG_performance_analysis.md"
echo ""
echo "The old data was backed up. Check data/backups/ for the archive."
