#!/bin/bash
# bin/manage-backup.sh
#
# Creates and restores backups of the ChromaDB vector database.
#
# The ChromaDB data lives in a Docker named volume (chroma_data).
# Backups are written to data/backups/ as timestamped .tar.gz archives.
# The chroma container is paused during dump to guarantee a consistent snapshot.
#
# Usage:
#   bin/manage-backup.sh --dump              # create a new backup
#   bin/manage-backup.sh --dump -y           # create a backup (non-interactive)
#   bin/manage-backup.sh --restore           # interactively restore a backup
#   bin/manage-backup.sh --restore <file>    # restore a specific archive
#   bin/manage-backup.sh --restore <file> -y # restore without confirmation prompts
#   bin/manage-backup.sh --list              # list available backups

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

source "$SCRIPT_DIR/common.sh"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Docker Compose project name (prefix used for volume names).
# Defaults to the directory name, matching Docker Compose's own default.
COMPOSE_PROJECT="${COMPOSE_PROJECT_NAME:-$(basename "$PROJECT_ROOT")}"
VOLUME_NAME="${COMPOSE_PROJECT}_chroma_data"
CONTAINER_NAME="chroma"

BACKUP_DIR="${PROJECT_ROOT}/data/backups"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
# BACKUP_FILE is computed after load_env (see Entrypoint section) so that
# EMBEDDING_MODEL_NAME from .env is available for the filename.

# Whether to skip interactive confirmation prompts (set by -y flag)
AUTO_YES=false

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

usage() {
    echo "Usage: $(basename "$0") --dump [-y] | --restore [<file>] [-y] | --list"
    echo ""
    echo "  --dump              Pause ChromaDB, snapshot the volume, resume"
    echo "  --restore [<file>]  Restore from a backup archive (interactive if no file given)"
    echo "  --list              List available backups in data/backups/"
    echo "  -y                  Skip all confirmation prompts (for scripted use)"
    exit 1
}

require_docker() {
    if ! docker info &>/dev/null; then
        echo "❌ Docker is not running. Please start Docker and try again."
        exit 1
    fi
}

require_volume() {
    if ! docker volume inspect "$VOLUME_NAME" &>/dev/null; then
        echo "❌ Volume '$VOLUME_NAME' not found."
        echo "   Has the stack been started at least once? (docker compose up)"
        exit 1
    fi
}

list_backups() {
    local backups=()
    while IFS= read -r f; do
        [ -n "$f" ] && backups+=("$f")
    done < <(find "$BACKUP_DIR" -maxdepth 1 -name "chroma_backup_*.tar.gz" | sort -r 2>/dev/null)
    printf '%s\n' "${backups[@]}"
}

human_size() {
    # Prints the file size in a human-readable format (macOS + GNU compatible)
    if du --version &>/dev/null 2>&1; then
        du -sh "$1" | cut -f1   # GNU
    else
        du -sh "$1" | cut -f1   # macOS
    fi
}

# ---------------------------------------------------------------------------
# --list
# ---------------------------------------------------------------------------

cmd_list() {
    if [ ! -d "$BACKUP_DIR" ] || [ -z "$(list_backups)" ]; then
        echo "ℹ️  No backups found in ${BACKUP_DIR}/"
        exit 0
    fi
    echo "📦 Available backups in ${BACKUP_DIR}/:"
    echo "----------------------------------------------------------------"
    while IFS= read -r f; do
        size=$(human_size "$f")
        printf "  %-50s  %s\n" "$(basename "$f")" "$size"
    done < <(list_backups)
}

# ---------------------------------------------------------------------------
# --dump
# ---------------------------------------------------------------------------

cmd_dump() {
    require_docker
    require_volume

    mkdir -p "$BACKUP_DIR"

    echo "🗄️  ChromaDB Backup"
    echo "   Volume  : $VOLUME_NAME"
    echo "   Output  : $BACKUP_FILE"
    echo ""

    # Check whether the chroma container is running so we can pause/unpause it.
    local chroma_running=false
    if docker inspect --format '{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null | grep -q "true"; then
        chroma_running=true
    fi

    if [ "$chroma_running" = true ]; then
        echo "⏸️  Pausing ChromaDB container for a consistent snapshot..."
        docker pause "$CONTAINER_NAME" >/dev/null
    else
        echo "ℹ️  ChromaDB container is not running — skipping pause."
    fi

    echo "📦 Creating archive..."
    docker run --rm \
        -v "${VOLUME_NAME}:/data:ro" \
        -v "${BACKUP_DIR}:/backup" \
        alpine \
        tar czf "/backup/$(basename "$BACKUP_FILE")" -C /data .

    if [ "$chroma_running" = true ]; then
        echo "▶️  Resuming ChromaDB container..."
        docker unpause "$CONTAINER_NAME" >/dev/null
    fi

    SIZE=$(human_size "$BACKUP_FILE")

    # Write a metadata sidecar file with model name and current thresholds.
    # This is purely informational — users can reference it when restoring to
    # check which thresholds were in effect when the backup was made.
    META_FILE="${BACKUP_FILE%.tar.gz}.meta.txt"
    cat > "$META_FILE" <<EOF
# ChromaDB Backup Metadata
# Created: $(date '+%Y-%m-%d %H:%M:%S')
#
# HOW TO USE THIS FILE WHEN RESTORING
# ------------------------------------
# EMBEDDING_MODEL_NAME: The embedding model that was active when this backup was
#   made. After restoring, ensure your .env uses the SAME model before re-ingesting.
#   Restoring with a different model will produce incorrect search results.
#   To switch models safely: bin/switch-embedding-model.sh <model>
#
# TM_THRESHOLD / GLOSSARY_THRESHOLD / RAG_STRICT_DISTANCE_THRESHOLD:
#   The RAG threshold values calibrated for this model at the time of backup.
#   After restoring and re-ingesting, you can copy these values back into .env
#   to restore previous performance — or run bin/analyse.sh to recalibrate.
#
# See docs/7_embedding_model.md for guidance on model switching.
# See docs/3_RAG_performance_analysis.md for threshold recalibration.
EMBEDDING_MODEL_NAME=${EMBEDDING_MODEL_NAME:-BAAI/bge-large-en-v1.5}
TM_THRESHOLD=${TM_THRESHOLD:-}
GLOSSARY_THRESHOLD=${GLOSSARY_THRESHOLD:-}
RAG_STRICT_DISTANCE_THRESHOLD=${RAG_STRICT_DISTANCE_THRESHOLD:-}
EOF

    echo ""
    echo "✅ Backup complete: $(basename "$BACKUP_FILE") (${SIZE})"
    echo "   Metadata : $(basename "$META_FILE")"
}

# ---------------------------------------------------------------------------
# --restore
# ---------------------------------------------------------------------------

cmd_restore() {
    local target_file="$1"

    require_docker
    require_volume

    # If no file was specified, prompt the user to pick one.
    if [ -z "$target_file" ]; then
        local backups=()
        while IFS= read -r f; do
            [ -n "$f" ] && backups+=("$(basename "$f")")
        done < <(list_backups)

        if [ ${#backups[@]} -eq 0 ]; then
            echo "❌ No backups found in ${BACKUP_DIR}/"
            echo "   Run: bin/manage-backup.sh --dump"
            exit 1
        fi

        echo "📦 Available backups (newest first):"
        echo "----------------------------------------------------------------"
        PS3="Select backup to restore: "
        select chosen in "${backups[@]}"; do
            if [ -n "$chosen" ]; then
                target_file="${BACKUP_DIR}/${chosen}"
                break
            fi
            echo "❌ Invalid option. Please try again."
        done
    fi

    if [ ! -f "$target_file" ]; then
        echo "❌ File not found: $target_file"
        exit 1
    fi

    # --- Model mismatch check ---
    # Extract the model short name from the filename and compare to current config.
    # Filenames: chroma_backup_YYYYMMDD_HHMMSS_<model-short>.tar.gz
    backup_model=$(basename "$target_file" .tar.gz | sed 's/^chroma_backup_[0-9]*_[0-9]*_//')
    current_model=$(echo "${EMBEDDING_MODEL_NAME:-BAAI/bge-large-en-v1.5}" | sed 's|.*/||')

    if [ -n "$backup_model" ] && [ "$backup_model" != "$current_model" ]; then
        echo ""
        echo "⚠️  EMBEDDING MODEL MISMATCH"
        echo "   Backup was created with : $backup_model"
        echo "   Current config uses     : $current_model"
        echo "   Restoring this backup will produce incorrect search results."
        echo "   After restore, you must re-ingest all data with the backup's model."
        echo ""
        if [ "$AUTO_YES" = true ]; then
            echo "   (-y flag set — proceeding anyway)"
        else
            read -rp "   Type 'yes' to proceed anyway: " mismatch_confirm
            if [ "$mismatch_confirm" != "yes" ]; then
                echo "❌ Restore cancelled."
                exit 1
            fi
        fi
    fi

    echo ""
    echo "⚠️  WARNING: This will OVERWRITE all data in volume '$VOLUME_NAME'."
    echo "   Restoring from: $(basename "$target_file")"
    if [ "$AUTO_YES" = true ]; then
        echo "   (-y flag set — skipping confirmation)"
    else
        read -rp "   Type 'yes' to confirm: " confirmation
        if [ "$confirmation" != "yes" ]; then
            echo "❌ Restore cancelled."
            exit 1
        fi
    fi

    # Stop the chroma container (not just pause) before modifying volume data.
    local chroma_running=false
    if docker inspect --format '{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null | grep -q "true"; then
        chroma_running=true
    fi

    if [ "$chroma_running" = true ]; then
        echo ""
        echo "🛑 Stopping ChromaDB container before restore..."
        docker compose stop chroma
    fi

    echo "🔄 Restoring volume from archive..."
    docker run --rm \
        -v "${VOLUME_NAME}:/data" \
        -v "$(dirname "$target_file"):/backup:ro" \
        alpine \
        sh -c "rm -rf /data/* /data/..?* /data/.[!.]* 2>/dev/null; tar xzf /backup/$(basename "$target_file") -C /data"

    if [ "$chroma_running" = true ]; then
        echo "▶️  Restarting ChromaDB container..."
        docker compose start chroma
    fi

    echo ""
    echo "✅ Restore complete from: $(basename "$target_file")"
    echo "   If other services were stopped, restart the full stack with: docker compose up -d"
}

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

cd "$PROJECT_ROOT"
load_env

# Re-derive BACKUP_FILE now that .env is loaded (EMBEDDING_MODEL_NAME may have changed)
MODEL_SHORT="$(echo "${EMBEDDING_MODEL_NAME:-BAAI/bge-large-en-v1.5}" | sed 's|.*/||')"
BACKUP_FILE="${BACKUP_DIR}/chroma_backup_${TIMESTAMP}_${MODEL_SHORT}.tar.gz"

# Parse flags: shift through args to find -y
REMAINING_ARGS=()
for arg in "$@"; do
    case "$arg" in
        -y) AUTO_YES=true ;;
        *)  REMAINING_ARGS+=("$arg") ;;
    esac
done

case "${REMAINING_ARGS[0]:-}" in
    --dump)    cmd_dump ;;
    --restore) cmd_restore "${REMAINING_ARGS[1]:-}" ;;
    --list)    cmd_list ;;
    *)         usage ;;
esac
