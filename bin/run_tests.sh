#!/bin/bash

set -e

# Define colors for output (Standard shell assignment: no spaces)
GREEN='\033[0;32m'
NC='\033[0m' # No Color

echo -e "${GREEN}Starting all tests within the toolbox container...${NC}"

# 1. -p no:cacheprovider: Disables the pytest cache to avoid permission errors.
# 2. PYTHONPATH: We add the rag-proxy src path so integration tests can find 'app'.
docker compose exec \
  -e PYTHONPATH="/app/src:/app/services/rag-proxy/src:/app/shared" \
  toolbox python -m pytest \
  -p no:cacheprovider \
  --maxfail=2 \
  --import-mode=importlib \
  "$@"

echo -e "${GREEN}Tests completed successfully.${NC}"
