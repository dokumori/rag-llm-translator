#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Define paths
LOG_FILE_HOST="services/toolbox/src/translation.jsonl"
LOG_FILE_CONTAINER="/app/src/translation.jsonl"
ANALYZER_SCRIPT="/app/src/analyze_logs.py"

# Near Misses Paths
MISSES_CSV_HOST="data/rag-analysis/near_misses.csv"
MISSES_CSV_CONTAINER="/app/data/rag-analysis/near_misses.csv"

# Matches Paths
MATCHES_CSV_HOST="data/rag-analysis/matches.csv"
MATCHES_CSV_CONTAINER="/app/data/rag-analysis/matches.csv"

# 1. Prepare host directories
mkdir -p services/toolbox/src
mkdir -p data/rag-analysis

echo "📊 Capturing logs from rag-proxy..."
docker compose logs rag-proxy > "$LOG_FILE_HOST"

echo "🚀 Running analysis inside toolbox container..."
docker compose exec toolbox python3 "$ANALYZER_SCRIPT" "$LOG_FILE_CONTAINER"

echo "📥 Copying Reports to host..."

# Copy Near Misses (Allow failure with || true)
docker compose cp toolbox:"$MISSES_CSV_CONTAINER" "$MISSES_CSV_HOST" 2>/dev/null || true
if [ -f "$MISSES_CSV_HOST" ]; then
  echo "✅ Saved: $MISSES_CSV_HOST"
else
  echo "ℹ️  No 'near_misses.csv' found (Good! No close rejects)."
fi

# Copy Matches (Allow failure with || true)
docker compose cp toolbox:"$MATCHES_CSV_CONTAINER" "$MATCHES_CSV_HOST" 2>/dev/null || true
if [ -f "$MATCHES_CSV_HOST" ]; then
  echo "✅ Saved: $MATCHES_CSV_HOST"
else
  echo "ℹ️  No 'matches.csv' found (Check analysis output above to confirm 0 matches)."
fi
