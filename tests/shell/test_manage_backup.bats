#!/usr/bin/env bats
# tests/shell/test_manage_backup.bats
#
# Unit tests for string-manipulation and argument-parsing logic in
# bin/manage-backup.sh. Docker-dependent functions (cmd_dump, cmd_restore,
# cmd_list) are NOT tested here.

load test_helper

# ---------------------------------------------------------------------------
# MODEL_SHORT extraction (line 296 of manage-backup.sh)
#   echo "$EMBEDDING_MODEL_NAME" | sed 's|.*/||'
# ---------------------------------------------------------------------------

_model_short() {
    echo "$1" | sed 's|.*/||'
}

@test "[manage-backup.sh::MODEL_SHORT] strips org prefix" {
    run _model_short "BAAI/bge-large-en-v1.5"
    assert_success
    assert_output "bge-large-en-v1.5"
}

@test "[manage-backup.sh::MODEL_SHORT] handles no prefix" {
    run _model_short "all-MiniLM-L6-v2"
    assert_success
    assert_output "all-MiniLM-L6-v2"
}

# ---------------------------------------------------------------------------
# backup_model extraction from filename (line 224 of manage-backup.sh)
#   basename "$target_file" .tar.gz | sed 's/^chroma_backup_[0-9]*_[0-9]*_//'
# ---------------------------------------------------------------------------

_extract_backup_model() {
    basename "$1" .tar.gz | sed 's/^chroma_backup_[0-9]*_[0-9]*_//'
}

@test "[manage-backup.sh::backup_model] extracts model from filename" {
    run _extract_backup_model "chroma_backup_20260518_120000_bge-large-en-v1.5.tar.gz"
    assert_success
    assert_output "bge-large-en-v1.5"
}

@test "[manage-backup.sh::backup_model] handles empty model portion" {
    run _extract_backup_model "chroma_backup_20260518_120000_.tar.gz"
    assert_success
    assert_output ""
}

# ---------------------------------------------------------------------------
# Argument parsing: -y flag extraction (lines 300–306 of manage-backup.sh)
# ---------------------------------------------------------------------------

# Stub duplicated from manage-backup.sh so the argument-parsing logic can be
# tested in isolation without sourcing (and executing) the full script.
# TODO: extract this logic into bin/lib/backup_helpers.sh so it can be sourced
# directly — testing a copy risks the stub silently diverging from the real code.
_parse_args() {
    local AUTO_YES=false
    local REMAINING_ARGS=()
    for arg in "$@"; do
        case "$arg" in
            -y) AUTO_YES=true ;;
            *)  REMAINING_ARGS+=("$arg") ;;
        esac
    done
    echo "AUTO_YES=$AUTO_YES"
    echo "REMAINING=${REMAINING_ARGS[*]}"
}

@test "[manage-backup.sh::argument_parsing] extracts -y flag" {
    run _parse_args --dump -y
    assert_success
    assert_line "AUTO_YES=true"
    assert_line "REMAINING=--dump"
}

@test "[manage-backup.sh::argument_parsing] without -y" {
    run _parse_args --restore file.tar.gz
    assert_success
    assert_line "AUTO_YES=false"
    assert_line "REMAINING=--restore file.tar.gz"
}

# ---------------------------------------------------------------------------
# list_backups: finds and sorts archives (lines 72–78 of manage-backup.sh)
# ---------------------------------------------------------------------------

@test "[manage-backup.sh::list_backups] finds and sorts archives newest-first" {
    local tmpdir="${BATS_TEST_TMPDIR}/backups_test"
    mkdir -p "$tmpdir"

    # Create dummy backup files with different timestamps in the names
    touch "$tmpdir/chroma_backup_20260101_000000_model.tar.gz"
    touch "$tmpdir/chroma_backup_20260301_000000_model.tar.gz"
    touch "$tmpdir/chroma_backup_20260201_000000_model.tar.gz"
    touch "$tmpdir/unrelated_file.txt"

    # Replicate the list_backups logic from manage-backup.sh
    BACKUP_DIR="$tmpdir"
    _list_backups() {
        local backups=()
        while IFS= read -r f; do
            [ -n "$f" ] && backups+=("$f")
        done < <(find "$BACKUP_DIR" -maxdepth 1 -name "chroma_backup_*.tar.gz" | sort -r 2>/dev/null)
        printf '%s\n' "${backups[@]}"
    }

    run _list_backups
    assert_success
    # Should have exactly 3 lines (no unrelated files)
    [ "${#lines[@]}" -eq 3 ]
    # Newest first
    assert_line --index 0 --partial "20260301"
    assert_line --index 1 --partial "20260201"
    assert_line --index 2 --partial "20260101"
}
