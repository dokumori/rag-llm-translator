#!/bin/bash
# bin/run_bash_tests.sh — Run BATS (Bash Automated Testing System) shell tests.
#
# Usage:
#   bin/run_bash_tests.sh                  # run all shell tests
#   bin/run_bash_tests.sh tests/shell/test_common.sh.bats  # run a specific file
#
# BATS is vendored as a Git submodule in tests/bats/bats-core/.
# If missing, run: git submodule update --init --recursive

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

BATS_BIN="${PROJECT_ROOT}/tests/bats/bats-core/bin/bats"

if [ ! -x "$BATS_BIN" ]; then
    echo "❌ BATS not found at: ${BATS_BIN}"
    echo "   Run: git submodule update --init --recursive"
    exit 1
fi

# Collect the list of files to run
if [ $# -gt 0 ]; then
    FILES=("$@")
else
    FILES=("${PROJECT_ROOT}/tests/shell/"*.bats)
fi

# ── Run each file and track results ──────────────────────────────────────────
passed_files=()
failed_files=()

for file in "${FILES[@]}"; do
    echo ""
    if "$BATS_BIN" --timing "$file"; then
        passed_files+=("$file")
    else
        failed_files+=("$file")
    fi
done

# ── Summary ───────────────────────────────────────────────────────────────────
total=$(( ${#passed_files[@]} + ${#failed_files[@]} ))
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Test Suite Summary  ($total file(s) run)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ ${#passed_files[@]} -gt 0 ]; then
    echo "  ✅ Passed (${#passed_files[@]}):"
    for f in "${passed_files[@]}"; do
        echo "     • $(basename "$f")"
    done
fi

if [ ${#failed_files[@]} -gt 0 ]; then
    echo "  ❌ Failed (${#failed_files[@]}):"
    for f in "${failed_files[@]}"; do
        echo "     • $(basename "$f")"
    done
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Exit with failure if any file failed
[ ${#failed_files[@]} -eq 0 ]
