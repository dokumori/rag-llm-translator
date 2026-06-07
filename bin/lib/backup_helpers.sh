#!/bin/bash
# bin/lib/backup_helpers.sh
#
# Shared helper functions for backup management.
# Sourced by bin/manage-backup.sh (and testable via BATS).
#
# Expected globals (must be set before calling where noted):
#   BACKUP_DIR — path to the backup directory (used by _list_backups)
#
# Global-setter functions (modify the caller's scope):
#   _parse_backup_args — sets AUTO_YES (string) and REMAINING_ARGS (array)
#
# ⚠️  _parse_backup_args sets globals. Do NOT invoke it via the BATS `run`
#     helper — `run` executes in a subshell and the globals will be lost.
#     Call it directly and assert on $AUTO_YES / ${REMAINING_ARGS[@]}.

# Strips an org prefix from a model name.
# Example: "BAAI/bge-large-en-v1.5" → "bge-large-en-v1.5"
#          "all-MiniLM-L6-v2"       → "all-MiniLM-L6-v2"
_model_short() {
    echo "$1" | sed 's|.*/||'
}

# Extracts the model short-name encoded in a backup filename for an 
# embedding model mismatch safety check, as the distance calculation 
# differs per model.
# Example: "chroma_backup_20260518_120000_bge-large-en-v1.5.tar.gz" → "bge-large-en-v1.5"
_extract_backup_model() {
    basename "$1" .tar.gz | sed 's/^chroma_backup_[0-9]*_[0-9]*_//'
}

# Parses backup script flags.
# Sets AUTO_YES=true when -y is present; all other args go into REMAINING_ARGS.
#
# Usage:
#   AUTO_YES=false
#   REMAINING_ARGS=()
#   _parse_backup_args "$@"
#
# ⚠️  Sets globals — do NOT call via BATS `run`.
_parse_backup_args() {
    AUTO_YES=false
    REMAINING_ARGS=()
    for arg in "$@"; do
        case "$arg" in
            -y) AUTO_YES=true ;;
            *)  REMAINING_ARGS+=("$arg") ;;
        esac
    done
}

# Lists backup archives in $BACKUP_DIR, sorted newest-first.
# Prints one absolute path per line; prints nothing if no archives exist.
#
# Requires: BACKUP_DIR — path to the backup directory
_list_backups() {
    local backups=()
    while IFS= read -r f; do
        [ -n "$f" ] && backups+=("$f")
    done < <(find "$BACKUP_DIR" -maxdepth 1 -name "chroma_backup_*.tar.gz" | sort -r 2>/dev/null)
    printf '%s\n' "${backups[@]}"
}
