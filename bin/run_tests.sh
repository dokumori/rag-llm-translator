#!/bin/bash
# run_tests.sh — Run the test suite inside the toolbox Docker container.
#
# Usage:
#   bin/run_tests.sh                   # unit tests only (integration tests skipped)
#   bin/run_tests.sh --integration     # unit tests + integration tests (requires stack up)
#   bin/run_tests.sh -k test_ingest    # pass any extra pytest flags through
#
# Integration tests require the full Docker stack to be running:
#   docker compose up -d

set -e

GREEN='\033[0;32m'
NC='\033[0m'

# Translate --integration into --run-integration (the pytest flag).
# All other arguments pass straight through to pytest.
PYTEST_EXTRA_ARGS=()
for arg in "$@"; do
  if [[ "$arg" == "--integration" ]]; then
    PYTEST_EXTRA_ARGS+=("--run-integration")
  else
    PYTEST_EXTRA_ARGS+=("$arg")
  fi
done

if [[ " ${PYTEST_EXTRA_ARGS[*]} " == *"--run-integration"* ]]; then
  echo -e "${GREEN}Running unit + integration tests inside toolbox container...${NC}"
else
  echo -e "${GREEN}Running unit tests inside toolbox container (integration tests skipped)...${NC}"
  echo -e "  → To include integration tests: bin/run_tests.sh --integration"
fi

# 1. -p no:cacheprovider: Disables the pytest cache to avoid permission errors.
# 2. PYTHONPATH: We add the rag-proxy src path so integration tests can find 'app'.
docker compose exec \
  -e PYTHONPATH="/app/src:/app/services/rag-proxy/src:/app/shared" \
  toolbox python -m pytest \
  -p no:cacheprovider \
  --maxfail=2 \
  --import-mode=importlib \
  "${PYTEST_EXTRA_ARGS[@]}"

echo -e "${GREEN}Tests completed successfully.${NC}"
