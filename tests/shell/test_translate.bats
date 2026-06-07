#!/usr/bin/env bats
# tests/shell/test_translate.bats
#
# Unit tests for the MODEL_SLUG construction logic in bin/lib/translate_helpers.sh.

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
