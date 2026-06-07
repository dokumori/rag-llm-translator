#!/usr/bin/env bats
# tests/shell/test_manage_backup.bats
#
# Unit tests for string-manipulation and argument-parsing logic in
# bin/lib/backup_helpers.sh. Docker-dependent functions (cmd_dump, cmd_restore,
# cmd_list) are NOT tested here.

load test_helper

setup() {
    source "${PROJECT_ROOT}/bin/lib/backup_helpers.sh"
}

# ---------------------------------------------------------------------------
# _model_short
# ---------------------------------------------------------------------------

@test "[backup_helpers.sh::_model_short] strips org prefix" {
    run _model_short "BAAI/bge-large-en-v1.5"
    assert_success
    assert_output "bge-large-en-v1.5"
}

@test "[backup_helpers.sh::_model_short] handles no prefix" {
    run _model_short "all-MiniLM-L6-v2"
    assert_success
    assert_output "all-MiniLM-L6-v2"
}

# ---------------------------------------------------------------------------
# _extract_backup_model
# ---------------------------------------------------------------------------

@test "[backup_helpers.sh::_extract_backup_model] extracts model from filename" {
    run _extract_backup_model "chroma_backup_20260518_120000_bge-large-en-v1.5.tar.gz"
    assert_success
    assert_output "bge-large-en-v1.5"
}

@test "[backup_helpers.sh::_extract_backup_model] handles empty model portion" {
    run _extract_backup_model "chroma_backup_20260518_120000_.tar.gz"
    assert_success
    assert_output ""
}

# ---------------------------------------------------------------------------
# _parse_backup_args
# NOTE: _parse_backup_args sets globals (AUTO_YES, REMAINING_ARGS).
# Do NOT use `run` — it executes in a subshell and globals will be lost.
# ---------------------------------------------------------------------------

@test "[backup_helpers.sh::_parse_backup_args] extracts -y flag" {
    AUTO_YES=false
    REMAINING_ARGS=()
    _parse_backup_args --dump -y
    assert_equal "$AUTO_YES" "true"
    assert_equal "${REMAINING_ARGS[*]}" "--dump"
}

@test "[backup_helpers.sh::_parse_backup_args] without -y" {
    AUTO_YES=false
    REMAINING_ARGS=()
    _parse_backup_args --restore file.tar.gz
    assert_equal "$AUTO_YES" "false"
    assert_equal "${REMAINING_ARGS[0]}" "--restore"
    assert_equal "${REMAINING_ARGS[1]}" "file.tar.gz"
}

@test "[backup_helpers.sh::_parse_backup_args] no args" {
    AUTO_YES=false
    REMAINING_ARGS=()
    _parse_backup_args
    assert_equal "$AUTO_YES" "false"
    assert_equal "${#REMAINING_ARGS[@]}" "0"
}

# ---------------------------------------------------------------------------
# _list_backups
# ---------------------------------------------------------------------------

@test "[backup_helpers.sh::_list_backups] finds and sorts archives newest-first" {
    local tmpdir="${BATS_TEST_TMPDIR}/backups_test"
    mkdir -p "$tmpdir"

    # Create dummy backup files with different timestamps in the names
    touch "$tmpdir/chroma_backup_20260101_000000_model.tar.gz"
    touch "$tmpdir/chroma_backup_20260301_000000_model.tar.gz"
    touch "$tmpdir/chroma_backup_20260201_000000_model.tar.gz"
    touch "$tmpdir/unrelated_file.txt"

    BACKUP_DIR="$tmpdir"
    run _list_backups
    assert_success
    # Should have exactly 3 lines (no unrelated files)
    assert_equal "${#lines[@]}" "3"
    # Newest first
    assert_line --index 0 --partial "20260301"
    assert_line --index 1 --partial "20260201"
    assert_line --index 2 --partial "20260101"
}

@test "[backup_helpers.sh::_list_backups] returns empty for no archives" {
    local tmpdir="${BATS_TEST_TMPDIR}/backups_empty"
    mkdir -p "$tmpdir"

    BACKUP_DIR="$tmpdir"
    run _list_backups
    assert_success
    assert_output ""
}
