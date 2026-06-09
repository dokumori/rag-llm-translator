#!/usr/bin/env bats
# tests/shell/test_translate.bats
#
# Unit tests for:
#   - MODEL_SLUG construction logic in bin/lib/translate_helpers.sh
#   - Regression guard: multi-language loop must not abort when post_process exits non-zero

load test_helper

setup() {
    source "${PROJECT_ROOT}/bin/lib/translate_helpers.sh"
}

@test "[translate_helpers.sh::_compute_model_slug] dry run" {
    run _compute_model_slug "anything" "true"
    assert_success
    assert_output "dry-run"
}

@test "[translate_helpers.sh::_compute_model_slug] simple model name" {
    run _compute_model_slug "gpt-4o" "false"
    assert_success
    assert_output "gpt-4o"
}

@test "[translate_helpers.sh::_compute_model_slug] model with spaces and uppercase" {
    run _compute_model_slug "Claude 3.5 Haiku" "false"
    assert_success
    assert_output "claude-3-5-haiku"
}

@test "[translate_helpers.sh::_compute_model_slug] model with special characters (em-dash)" {
    run _compute_model_slug "Ollama — llama3.1" "false"
    assert_success
    assert_output "ollama-llama3-1"
}

@test "[translate_helpers.sh::_compute_model_slug] strips leading and trailing hyphens" {
    run _compute_model_slug "--test--" "false"
    assert_success
    assert_output "test"
}

# ---------------------------------------------------------------------------
# post_process.py exits 1 when no output files are found — a legitimate
# "nothing to do" condition. The || true inside _post_process_lang is
# load-bearing: translate.sh runs under set -e, so without it the
# multi-language loop would abort after the first language.
#
# These tests source the real translate_helpers.sh and stub `docker` so
# no container is needed. If the || true is ever removed from
# _post_process_lang, the first test fails immediately.
# ---------------------------------------------------------------------------

@test "[translate_helpers.sh::_post_process_lang] does not abort under set -e when docker exits 1" {
    # Stub docker to simulate post_process.py finding no output files (exit 1).
    docker() { return 1; }
    export -f docker

    run bash -c "
        source '${PROJECT_ROOT}/bin/lib/translate_helpers.sh'
        set -e
        _post_process_lang '/app/po/output/ja' 'ja'
        echo 'survived'
    "
    assert_success
    assert_output "survived"
}

@test "[translate_helpers.sh::_post_process_lang] passes output dir and lang to docker compose" {
    # Verify the correct arguments are forwarded so a refactor can't
    # silently drop a parameter.
    docker() {
        # Capture the full command line and print it so we can assert on it.
        echo "docker $*"
        return 0
    }
    export -f docker

    run bash -c "
        source '${PROJECT_ROOT}/bin/lib/translate_helpers.sh'
        _post_process_lang '/app/po/output/ja' 'ja'
    "
    assert_success
    assert_output --partial "post_process.py /app/po/output/ja --lang ja"
}

@test "[translate_helpers.sh::_post_process_lang] regression guard: without || true, set -e aborts on exit 1" {
    # This test documents the pre-fix behaviour: if the || true were removed,
    # a failing post_process call would kill the caller's set -e subshell.
    # If THIS test starts failing it means bash no longer aborts on a non-zero
    # exit in set -e context — the || true would then be unnecessary.
    docker() { return 1; }
    export -f docker

    run bash -c "
        source '${PROJECT_ROOT}/bin/lib/translate_helpers.sh'
        set -e
        # Call the inner docker command directly (bypassing || true) to
        # confirm that the failure would propagate without the guard.
        docker compose exec toolbox python3 /app/src/post_process.py '/app/po/output/ja' --lang 'ja'
        echo 'survived'
    "
    assert_failure
    refute_output --partial "survived"
}
