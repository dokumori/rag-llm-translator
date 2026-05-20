# tests/shell/test_helper.bash
# Common setup for all BATS test files.

# Locate the bats helper libraries relative to this file.
BATS_TEST_DIRNAME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BATS_LIB="${BATS_TEST_DIRNAME}/../bats"

load "${BATS_LIB}/bats-support/load"
load "${BATS_LIB}/bats-assert/load"

# Project root (two levels up from tests/shell/)
PROJECT_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
