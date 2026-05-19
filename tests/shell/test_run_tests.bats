#!/usr/bin/env bats
# tests/shell/test_run_tests.bats
#
# Unit tests for the --integration → --run-integration flag translation
# logic in bin/run_tests.sh (lines 19–26).

load test_helper

# Stub replicating the flag translation logic from run_tests.sh (lines 19–26)
# so it can be tested without sourcing (and executing) the full script.
# TODO: extract this logic into bin/lib/helpers.sh so it can be sourced
# directly — testing a copy risks the stub silently diverging from the real code.
_translate_args() {
    local PYTEST_EXTRA_ARGS=()
    for arg in "$@"; do
        if [[ "$arg" == "--integration" ]]; then
            PYTEST_EXTRA_ARGS+=("--run-integration")
        else
            PYTEST_EXTRA_ARGS+=("$arg")
        fi
    done
    # Print one arg per line for assertion
    printf '%s\n' "${PYTEST_EXTRA_ARGS[@]}"
}

@test "[run_tests.sh::_translate_args] translates --integration to --run-integration" {
    run _translate_args --integration
    assert_success
    assert_output "--run-integration"
}

@test "[run_tests.sh::_translate_args] passes other args through unchanged" {
    run _translate_args -k test_ingest
    assert_success
    assert_line --index 0 "-k"
    assert_line --index 1 "test_ingest"
}

@test "[run_tests.sh::_translate_args] mixed args: --integration plus other flags" {
    run _translate_args --integration -k test_foo
    assert_success
    assert_line --index 0 "--run-integration"
    assert_line --index 1 "-k"
    assert_line --index 2 "test_foo"
}

@test "[run_tests.sh::_translate_args] no args produces empty output" {
    run _translate_args
    assert_success
    assert_output ""
}

@test "[run_tests.sh::_translate_args] --run-integration passes through unchanged" {
    run _translate_args --run-integration
    assert_success
    assert_output "--run-integration"
}
