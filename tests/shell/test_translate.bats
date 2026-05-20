#!/usr/bin/env bats
# tests/shell/test_translate.bats
#
# Unit tests for the MODEL_SLUG construction logic in bin/translate.sh
# (lines 177–182).

load test_helper

# Stub mirroring the inline MODEL_SLUG logic from translate.sh (lines 177–182)
# so it can be tested without sourcing (and executing) the full script.
# TODO: extract this logic into bin/lib/translate_helpers.sh so it can be sourced
# directly — testing a copy risks the stub silently diverging from the real code.
_compute_model_slug() {
    local selected_model="$1"
    local is_dry_run="$2"
    if [ "$is_dry_run" = "true" ]; then
        echo "dry-run"
    else
        echo "$selected_model" \
            | tr '[:upper:]' '[:lower:]' \
            | sed 's/[^a-z0-9]/-/g' \
            | sed 's/-\{2,\}/-/g' \
            | sed 's/^-//;s/-$//'
    fi
}

@test "[translate.sh::_compute_model_slug] dry run" {
    run _compute_model_slug "anything" "true"
    assert_success
    assert_output "dry-run"
}

@test "[translate.sh::_compute_model_slug] simple model name" {
    run _compute_model_slug "gpt-4o" "false"
    assert_success
    assert_output "gpt-4o"
}

@test "[translate.sh::_compute_model_slug] model with spaces and uppercase" {
    run _compute_model_slug "Claude 3.5 Haiku" "false"
    assert_success
    assert_output "claude-3-5-haiku"
}

@test "[translate.sh::_compute_model_slug] model with special characters (em-dash)" {
    run _compute_model_slug "Ollama — llama3.1" "false"
    assert_success
    assert_output "ollama-llama3-1"
}

@test "[translate.sh::_compute_model_slug] strips leading and trailing hyphens" {
    run _compute_model_slug "--test--" "false"
    assert_success
    assert_output "test"
}
