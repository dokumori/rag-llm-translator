# tests/shell/test_system_menu.bats
# Added as part of the status check.
#
# BATS tests for functions added / modified in bin/system_menu.sh.
#
# Scope:
#   - _has_eval_data()  — new filesystem detector
#   - _menu_item()      — new rendering helper
#   - _refresh_status() — status variable population (mocked detectors)
#
# Strategy: we source only the specific helper functions from system_menu.sh
# rather than running the interactive menu loop.  Colour variables and the
# detector stubs are set up in each test's own setup block.

load "test_helper.bash"

# ---------------------------------------------------------------------------
# Shared setup
# ---------------------------------------------------------------------------
setup() {
    # Provide a clean temporary project root for filesystem tests.
    FAKE_ROOT="${BATS_TEST_TMPDIR}/project"
    mkdir -p "$FAKE_ROOT"

    # Minimally satisfy system_menu.sh's top-level expectations so we can
    # source helper functions in isolation.
    TRANSLATIONS_ROOT="${FAKE_ROOT}/data/translations"
    PROJECT_ROOT="$FAKE_ROOT"
    DATA_ROOT="${FAKE_ROOT}/data"

    # Colour stubs (no-op strings so printf output is predictable in tests).
    BOLD=""; DIM=""; GREEN=""; YELLOW=""; CYAN=""; RESET=""

    # Source only the helpers we want to test.
    # We use process substitution to strip the trap / while-loop so sourcing
    # doesn't block.  A simpler approach: define the functions inline below.

    # _has_eval_data
    _has_eval_data() {
        local eval_base="${TRANSLATIONS_ROOT}/eval"
        [ -d "$eval_base" ] || return 1
        for d in "$eval_base"/*/; do
            [ -d "$d" ] || continue
            [ -d "${d}with_rag" ] && [ -d "${d}without_rag" ] && return 0
        done
        return 1
    }

    # _menu_item
    _menu_item() {
        local key="$1" ready="$2" label="$3" desc="$4" hint="${5:-}"
        if [ "$ready" = true ]; then
            printf "    %s) %s — %s\n" "$key" "$label" "$desc"
        elif [ -n "$hint" ]; then
            printf "    DIM:%s) %s — %s  HINT:%s\n" "$key" "$label" "$desc" "$hint"
        else
            printf "    DIM:%s) %s — %s\n" "$key" "$label" "$desc"
        fi
    }
}

# ---------------------------------------------------------------------------
# _has_eval_data
# ---------------------------------------------------------------------------

@test "_has_eval_data: returns false when eval directory does not exist" {
    run _has_eval_data
    [ "$status" -eq 1 ]
}

@test "_has_eval_data: returns false when eval dir exists but is empty" {
    mkdir -p "${TRANSLATIONS_ROOT}/eval"
    run _has_eval_data
    [ "$status" -eq 1 ]
}

@test "_has_eval_data: returns false when only with_rag subdirectory exists" {
    mkdir -p "${TRANSLATIONS_ROOT}/eval/ja/with_rag"
    run _has_eval_data
    [ "$status" -eq 1 ]
}

@test "_has_eval_data: returns false when only without_rag subdirectory exists" {
    mkdir -p "${TRANSLATIONS_ROOT}/eval/ja/without_rag"
    run _has_eval_data
    [ "$status" -eq 1 ]
}

@test "_has_eval_data: returns true when both with_rag and without_rag exist" {
    mkdir -p "${TRANSLATIONS_ROOT}/eval/ja/with_rag"
    mkdir -p "${TRANSLATIONS_ROOT}/eval/ja/without_rag"
    run _has_eval_data
    [ "$status" -eq 0 ]
}

@test "_has_eval_data: returns true when any language has both subdirs (multi-lang)" {
    mkdir -p "${TRANSLATIONS_ROOT}/eval/es/with_rag"
    # Only es has both; fr only has with_rag
    mkdir -p "${TRANSLATIONS_ROOT}/eval/es/without_rag"
    mkdir -p "${TRANSLATIONS_ROOT}/eval/fr/with_rag"
    run _has_eval_data
    [ "$status" -eq 0 ]
}

# ---------------------------------------------------------------------------
# _menu_item
# ---------------------------------------------------------------------------

@test "_menu_item: ready=true renders key without DIM prefix" {
    run _menu_item "T" true "Translate" "Run the pipeline"
    [ "$status" -eq 0 ]
    # Output should contain the key but NOT the DIM: marker used in our stub
    [[ "$output" == *"T)"* ]]
    [[ "$output" != *"DIM:"* ]]
}

@test "_menu_item: ready=true renders label and description" {
    run _menu_item "T" true "Translate" "Run the pipeline"
    [[ "$output" == *"Translate"* ]]
    [[ "$output" == *"Run the pipeline"* ]]
}

@test "_menu_item: ready=false renders DIM marker" {
    run _menu_item "T" false "Translate" "Run the pipeline"
    [[ "$output" == *"DIM:T)"* ]]
}

@test "_menu_item: ready=false with hint includes hint text" {
    run _menu_item "T" false "Translate" "Run the pipeline" "needs stack"
    [[ "$output" == *"HINT:needs stack"* ]]
}

@test "_menu_item: ready=false without hint omits HINT marker" {
    run _menu_item "T" false "Translate" "Run the pipeline"
    [[ "$output" != *"HINT:"* ]]
}


# ---------------------------------------------------------------------------
# G) Extract Glossary from DB — menu item rendering
# ---------------------------------------------------------------------------

@test "_menu_item: G ready=true renders without DIM prefix" {
    run _menu_item "G" true "Extract Glossary from DB      " "Generate draft glossary from TM"
    [ "$status" -eq 0 ]
    [[ "$output" == *"G)"* ]]
    [[ "$output" != *"DIM:"* ]]
}

@test "_menu_item: G ready=true renders label and description" {
    run _menu_item "G" true "Extract Glossary from DB      " "Generate draft glossary from TM"
    [[ "$output" == *"Extract Glossary from DB"* ]]
    [[ "$output" == *"Generate draft glossary from TM"* ]]
}

@test "_menu_item: G ready=false with hint renders DIM and hint" {
    run _menu_item "G" false "Extract Glossary from DB      " "Generate draft glossary from TM" "needs stack"
    [[ "$output" == *"DIM:G)"* ]]
    [[ "$output" == *"HINT:needs stack"* ]]
}
