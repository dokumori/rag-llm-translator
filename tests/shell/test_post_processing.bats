#!/usr/bin/env bats
# tests/shell/test_post_processing.bats
#
# Unit tests for _build_plugin_lines and _patch_env from bin/lib/env_helpers.sh.

load test_helper

setup() {
    source "${PROJECT_ROOT}/bin/lib/env_helpers.sh"
}

# ---------------------------------------------------------------------------
# _build_plugin_lines
# ---------------------------------------------------------------------------

@test "[env_helpers.sh::_build_plugin_lines] single language config" {
    LANG_KEYS=(ja)
    LANG_VALS=(spacing_around_drupal_variables)

    run _build_plugin_lines
    assert_success
    assert_output "POST_PROCESS_PLUGINS_JA=spacing_around_drupal_variables"
}

@test "[env_helpers.sh::_build_plugin_lines] multiple languages" {
    LANG_KEYS=(ja es)
    LANG_VALS=("plugin_a,plugin_b" "plugin_c")

    run _build_plugin_lines
    assert_success
    assert_line --index 0 "POST_PROCESS_PLUGINS_JA=plugin_a,plugin_b"
    assert_line --index 1 "POST_PROCESS_PLUGINS_ES=plugin_c"
}

@test "[env_helpers.sh::_build_plugin_lines] language with hyphen" {
    LANG_KEYS=(pt-br)
    LANG_VALS=(plugin_a)

    run _build_plugin_lines
    assert_success
    assert_output "POST_PROCESS_PLUGINS_PT_BR=plugin_a"
}

@test "[env_helpers.sh::_build_plugin_lines] empty value" {
    LANG_KEYS=(ja)
    LANG_VALS=("")

    run _build_plugin_lines
    assert_success
    assert_output "POST_PROCESS_PLUGINS_JA="
}

# ---------------------------------------------------------------------------
# _patch_env
# ---------------------------------------------------------------------------

@test "[env_helpers.sh::_patch_env] adds PP block to clean .env" {
    local tmpdir="${BATS_TEST_TMPDIR}/patchenv1"
    mkdir -p "$tmpdir"
    echo "FOO=bar" > "$tmpdir/.env"

    ENV_FILE="$tmpdir/.env"
    PROJECT_ROOT="$tmpdir"

    _patch_env "true" "POST_PROCESS_PLUGINS_JA=spacing"

    # FOO=bar should be preserved
    run grep -q "^FOO=bar" "$ENV_FILE"
    assert_success
    # New block should be appended
    run grep -q "^POST_PROCESSING_ENABLED=true" "$ENV_FILE"
    assert_success
    run grep -q "^POST_PROCESS_PLUGINS_JA=spacing" "$ENV_FILE"
    assert_success
    run grep -q "^# --- Post-Processing" "$ENV_FILE"
    assert_success
}

@test "[env_helpers.sh::_patch_env] replaces existing PP block" {
    local tmpdir="${BATS_TEST_TMPDIR}/patchenv2"
    mkdir -p "$tmpdir"
    cat > "$tmpdir/.env" <<'EOF'
FOO=bar
POST_PROCESSING_ENABLED=false
POST_PROCESS_PLUGINS_JA=old_plugin
EOF

    ENV_FILE="$tmpdir/.env"
    PROJECT_ROOT="$tmpdir"

    _patch_env "true" "POST_PROCESS_PLUGINS_JA=new_plugin"

    # Old lines should be gone
    run grep -q "ENABLED=false" "$ENV_FILE"
    assert_failure
    run grep -q "old_plugin" "$ENV_FILE"
    assert_failure
    # New block present
    run grep -q "^POST_PROCESSING_ENABLED=true" "$ENV_FILE"
    assert_success
    run grep -q "^POST_PROCESS_PLUGINS_JA=new_plugin" "$ENV_FILE"
    assert_success
    # FOO preserved
    run grep -q "^FOO=bar" "$ENV_FILE"
    assert_success
}

@test "[env_helpers.sh::_patch_env] strips PP-related comments" {
    local tmpdir="${BATS_TEST_TMPDIR}/patchenv3"
    mkdir -p "$tmpdir"
    cat > "$tmpdir/.env" <<'EOF'
FOO=bar
# --- Post-Processing (old) ---
# POST_PROCESS_PLUGINS_JA=old
# See docs/2_post_processing.md
# ---- end ----
EOF

    ENV_FILE="$tmpdir/.env"
    PROJECT_ROOT="$tmpdir"

    _patch_env "false" ""

    # PP-related comments should be gone
    run grep -q "# --- Post-Processing (old)" "$ENV_FILE"
    assert_failure
    run grep -q "# POST_PROCESS_PLUGINS_" "$ENV_FILE"
    assert_failure
    run grep -q "# See docs/2_post_processing.md" "$ENV_FILE"
    assert_failure
    # New header is present
    run grep -q "^# --- Post-Processing (configured" "$ENV_FILE"
    assert_success
    run grep -q "^POST_PROCESSING_ENABLED=false" "$ENV_FILE"
    assert_success
}

@test "[env_helpers.sh::_patch_env] preserves unrelated comments" {
    local tmpdir="${BATS_TEST_TMPDIR}/patchenv4"
    mkdir -p "$tmpdir"
    cat > "$tmpdir/.env" <<'EOF'
# Regular comment about the project
FOO=bar
# Another comment
BAZ=qux
EOF

    ENV_FILE="$tmpdir/.env"
    PROJECT_ROOT="$tmpdir"

    _patch_env "true" ""

    # Unrelated comments should be preserved
    run grep -q "^# Regular comment about the project" "$ENV_FILE"
    assert_success
    run grep -q "^# Another comment" "$ENV_FILE"
    assert_success
    run grep -q "^FOO=bar" "$ENV_FILE"
    assert_success
    run grep -q "^BAZ=qux" "$ENV_FILE"
    assert_success
}
