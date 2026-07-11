#!/usr/bin/env bats
# tests/shell/test_cli_flags.bats
#
# Tests for the non-interactive CLI flags of bin/translate.sh and
# bin/eval_quality.sh. Only the argument-parsing layer is exercised here —
# it runs before common.sh is sourced and before any Docker call, so these
# tests need no containers. Model/language validation against real data is
# covered by tests/unit/test_model_config.py and integration runs.

load test_helper

# ---------------------------------------------------------------------------
# translate.sh
# ---------------------------------------------------------------------------

@test "[translate.sh] --help exits 0 and prints usage" {
    run bash "${PROJECT_ROOT}/bin/translate.sh" --help
    assert_success
    assert_output --partial "Usage:"
    assert_output --partial "--lang"
    assert_output --partial "--model"
}

@test "[translate.sh] unknown argument exits 1 with usage" {
    run bash "${PROJECT_ROOT}/bin/translate.sh" bogus
    assert_failure
    assert_output --partial "Unknown argument: bogus"
    assert_output --partial "Usage:"
}

@test "[translate.sh] --lang without a value exits 1" {
    run bash "${PROJECT_ROOT}/bin/translate.sh" --lang
    assert_failure
    assert_output --partial "--lang requires a value"
}

@test "[translate.sh] --model without a value exits 1" {
    run bash "${PROJECT_ROOT}/bin/translate.sh" --model
    assert_failure
    assert_output --partial "--model requires a value"
}

@test "[translate.sh] legacy -<lang> shorthand is accepted as a language flag" {
    # 'zz' is never a real language directory, so the script must fail at
    # language validation (proving -zz was parsed as --lang zz), not at
    # argument parsing.
    run bash "${PROJECT_ROOT}/bin/translate.sh" -zz
    assert_failure
    refute_output --partial "Unknown argument"
    assert_output --partial "zz"
}

# ---------------------------------------------------------------------------
# eval_quality.sh
# ---------------------------------------------------------------------------

@test "[eval_quality.sh] --help exits 0 and prints usage" {
    run bash "${PROJECT_ROOT}/bin/eval_quality.sh" --help
    assert_success
    assert_output --partial "Usage:"
    assert_output --partial "--limit"
}

@test "[eval_quality.sh] unknown argument exits 1 with usage" {
    run bash "${PROJECT_ROOT}/bin/eval_quality.sh" --bogus
    assert_failure
    assert_output --partial "Unknown argument: --bogus"
}

@test "[eval_quality.sh] --limit rejects a non-numeric value" {
    run bash "${PROJECT_ROOT}/bin/eval_quality.sh" --limit banana
    assert_failure
    assert_output --partial "--limit must be a positive number, 'all', or 'recommended'"
}

@test "[eval_quality.sh] --limit without a value exits 1" {
    run bash "${PROJECT_ROOT}/bin/eval_quality.sh" --limit
    assert_failure
    assert_output --partial "--limit requires a value"
}

@test "[eval_quality.sh] --lang without a value exits 1" {
    run bash "${PROJECT_ROOT}/bin/eval_quality.sh" --lang
    assert_failure
    assert_output --partial "--lang requires a value"
}
