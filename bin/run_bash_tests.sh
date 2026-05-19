#!/bin/bash
# bin/run_bash_tests.sh — Run BATS (Bash Automated Testing System) shell tests.
#
# Usage:
#   bin/run_bash_tests.sh                  # run all shell tests
#   bin/run_bash_tests.sh tests/shell/test_common.sh.bats  # run a specific file
#
# BATS is vendored as a Git submodule in tests/bats/bats-core/.
# If missing, run: git submodule update --init --recursive

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

BATS_BIN="${PROJECT_ROOT}/tests/bats/bats-core/bin/bats"

if [ ! -x "$BATS_BIN" ]; then
    echo "❌ BATS not found at: ${BATS_BIN}"
    echo "   Run: git submodule update --init --recursive"
    exit 1
fi

if [ $# -gt 0 ]; then
    # Run specific files passed as arguments
    "$BATS_BIN" --timing "$@"
else
    # Run all .bats files in tests/shell/
    "$BATS_BIN" --timing "${PROJECT_ROOT}/tests/shell/"*.bats
fi
