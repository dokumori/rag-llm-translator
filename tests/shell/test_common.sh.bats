#!/usr/bin/env bats
# tests/shell/test_common.sh.bats
#
# Unit tests for bin/common.sh path helpers, language discovery, and env loading.

load test_helper

setup() {
    # Source common.sh with default DATA_ROOT
    source "${PROJECT_ROOT}/bin/common.sh"
    # Record CWD so teardown can restore it (load_env tests use cd)
    _ORIGINAL_PWD="$(pwd)"
}

teardown() {
    cd "$_ORIGINAL_PWD"
}

# ---------------------------------------------------------------------------
# Path helpers (lines 22–26 of common.sh)
# ---------------------------------------------------------------------------

@test "[common.sh::tm_source_dir] returns correct path with default DATA_ROOT" {
    run tm_source_dir "ja"
    assert_success
    assert_output "data/tm_source/ja"
}

@test "[common.sh::glossary_path] appends glossary.csv" {
    run glossary_path "ja"
    assert_success
    assert_output "data/tm_source/ja/glossary.csv"
}

@test "[common.sh::input_dir] returns correct path" {
    run input_dir "es"
    assert_success
    assert_output "data/translations/input/es"
}

@test "[common.sh::output_dir] returns correct path" {
    run output_dir "es"
    assert_success
    assert_output "data/translations/output/es"
}

@test "[common.sh::eval_dir] returns correct path with hyphenated langcode" {
    run eval_dir "pt-br"
    assert_success
    assert_output "data/translations/eval/pt-br"
}


# ---------------------------------------------------------------------------
# discover_lang_dirs (bin/common.sh)
# ---------------------------------------------------------------------------

@test "[common.sh::discover_lang_dirs] finds non-hidden directories" {
    local tmpdir="${BATS_TEST_TMPDIR}/discover_test"
    mkdir -p "$tmpdir"/{ja,es,fr}

    run discover_lang_dirs "$tmpdir"
    assert_success
    assert_line "ja"
    assert_line "es"
    assert_line "fr"
}

@test "[common.sh::discover_lang_dirs] skips hidden directories" {
    local tmpdir="${BATS_TEST_TMPDIR}/discover_hidden"
    mkdir -p "$tmpdir"/{ja,.git,.hidden}

    run discover_lang_dirs "$tmpdir"
    assert_success
    assert_line "ja"
    refute_line ".git"
    refute_line ".hidden"
}

@test "[common.sh::discover_lang_dirs] returns empty for no subdirs" {
    local tmpdir="${BATS_TEST_TMPDIR}/discover_empty"
    mkdir -p "$tmpdir"

    run discover_lang_dirs "$tmpdir"
    assert_success
    assert_output ""
}

@test "[common.sh::discover_lang_dirs] returns empty for nonexistent dir" {
    run discover_lang_dirs "${BATS_TEST_TMPDIR}/does_not_exist"
    assert_success
    assert_output ""
}

# ---------------------------------------------------------------------------
# is_langcode (bin/common.sh)
# ---------------------------------------------------------------------------

@test "[common.sh::is_langcode] accepts 2-letter code" {
    run is_langcode "ja"
    assert_success
}

@test "[common.sh::is_langcode] accepts 3-letter code" {
    run is_langcode "fra"
    assert_success
}

@test "[common.sh::is_langcode] accepts hyphenated code" {
    run is_langcode "pt-br"
    assert_success
}

@test "[common.sh::is_langcode] accepts mixed-case subtag" {
    run is_langcode "zh-Hant"
    assert_success
}

@test "[common.sh::is_langcode] rejects utility dir names" {
    run is_langcode "with_rag"
    assert_failure
}

@test "[common.sh::is_langcode] rejects numeric strings" {
    run is_langcode "12345"
    assert_failure
}

@test "[common.sh::is_langcode] rejects single-char codes" {
    run is_langcode "a"
    assert_failure
}

@test "[common.sh::is_langcode] rejects empty string" {
    run is_langcode ""
    assert_failure
}

# ---------------------------------------------------------------------------
# list_available_langs (bin/common.sh)
# ---------------------------------------------------------------------------

@test "[common.sh::list_available_langs] finds langs with matching .po files" {
    local tmpdir="${BATS_TEST_TMPDIR}/langs_po"
    mkdir -p "$tmpdir"/{ja,es}
    touch "$tmpdir/ja/file.po"
    touch "$tmpdir/es/file.po"

    run list_available_langs "$tmpdir"
    assert_success
    assert_line "ja"
    assert_line "es"
}

@test "[common.sh::list_available_langs] skips dirs without matching extension" {
    local tmpdir="${BATS_TEST_TMPDIR}/langs_ext"
    mkdir -p "$tmpdir"/{ja,fr}
    touch "$tmpdir/ja/file.po"
    touch "$tmpdir/fr/file.txt"

    run list_available_langs "$tmpdir"
    assert_success
    assert_line "ja"
    refute_line "fr"
}

@test "[common.sh::list_available_langs] skips dirs that don't match langcode format" {
    local tmpdir="${BATS_TEST_TMPDIR}/langs_nonlang"
    mkdir -p "$tmpdir"/{ja,with_rag,debug,12345}
    touch "$tmpdir/ja/file.po"
    touch "$tmpdir/with_rag/file.po"
    touch "$tmpdir/debug/file.po"
    touch "$tmpdir/12345/file.po"

    run list_available_langs "$tmpdir"
    assert_success
    assert_line "ja"
    refute_line "with_rag"
    refute_line "debug"
    refute_line "12345"
}

@test "[common.sh::list_available_langs] uses custom extension" {
    local tmpdir="${BATS_TEST_TMPDIR}/langs_csv"
    mkdir -p "$tmpdir/ja"
    touch "$tmpdir/ja/file.csv"

    run list_available_langs "$tmpdir" ".csv"
    assert_success
    assert_line "ja"
}

@test "[common.sh::list_available_langs] finds langs with .po files in subdirectories (eval with_rag/without_rag structure)" {
    local tmpdir="${BATS_TEST_TMPDIR}/langs_subdirs"
    mkdir -p "$tmpdir/it/with_rag"
    mkdir -p "$tmpdir/it/without_rag"
    mkdir -p "$tmpdir/nl"
    touch "$tmpdir/it/with_rag/file.po"
    touch "$tmpdir/it/without_rag/file.po"
    # nl has no .po files at all — should be excluded

    run list_available_langs "$tmpdir"
    assert_success
    assert_line "it"
    refute_line "nl"
}


# ---------------------------------------------------------------------------
# load_env (lines 110–117 of common.sh)
# ---------------------------------------------------------------------------

@test "[common.sh::load_env] loads .env variables" {
    local tmpdir="${BATS_TEST_TMPDIR}/loadenv1"
    mkdir -p "$tmpdir"
    echo "FOO=bar" > "$tmpdir/.env"

    cd "$tmpdir"
    load_env
    [ "$FOO" = "bar" ]
}

@test "[common.sh::load_env] .env overrides .env.defaults" {
    local tmpdir="${BATS_TEST_TMPDIR}/loadenv2"
    mkdir -p "$tmpdir"
    echo "MY_VAR=default" > "$tmpdir/.env.defaults"
    echo "MY_VAR=override" > "$tmpdir/.env"

    cd "$tmpdir"
    load_env
    [ "$MY_VAR" = "override" ]
}

@test "[common.sh::load_env] skips comments" {
    local tmpdir="${BATS_TEST_TMPDIR}/loadenv3"
    mkdir -p "$tmpdir"
    cat > "$tmpdir/.env" <<'EOF'
# COMMENT=yes
REAL=value
EOF

    cd "$tmpdir"
    load_env
    [ "$REAL" = "value" ]
    [ -z "${COMMENT:-}" ]
}

@test "[common.sh::load_env] skips UID and GID" {
    local tmpdir="${BATS_TEST_TMPDIR}/loadenv4"
    mkdir -p "$tmpdir"
    local original_uid="$UID"
    cat > "$tmpdir/.env" <<'EOF'
UID=9999
GID=9999
VALID=yes
EOF

    cd "$tmpdir"
    load_env
    [ "$VALID" = "yes" ]
    # UID should NOT be overwritten to 9999
    [ "$UID" = "$original_uid" ]
}

@test "[common.sh::load_env] handles missing files gracefully" {
    local tmpdir="${BATS_TEST_TMPDIR}/loadenv5"
    mkdir -p "$tmpdir"
    # No .env or .env.defaults

    cd "$tmpdir"
    run load_env
    assert_success
}
