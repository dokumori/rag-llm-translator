#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Define paths
LOG_FILE_HOST="services/toolbox/src/translation.jsonl"
LOG_FILE_CONTAINER="/app/src/translation.jsonl"
ANALYZER_SCRIPT="/app/src/analyze_logs.py"
OUTPUT_CSV_HOST="data/rag-analysis/near_misses.csv"
OUTPUT_CSV_CONTAINER="/app/data/rag-analysis/near_misses.csv"

# 1. Prepare host directories
mkdir -p services/toolbox/src
mkdir -p data/rag-analysis

echo "📊 Capturing logs from rag-proxy..."
docker compose logs rag-proxy > "$LOG_FILE_HOST"

echo "🚀 Running analysis inside toolbox container..."
docker compose exec toolbox python3 "$ANALYZER_SCRIPT" "$LOG_FILE_CONTAINER"

echo "📥 Copying CSV to host..."
# This bypasses volume issues by forcing the file from the container to the host
docker compose cp toolbox:"$OUTPUT_CSV_CONTAINER" "$OUTPUT_CSV_HOST"

if [ -f "$OUTPUT_CSV_HOST" ]; then
  echo "✅ Success! File saved to: $OUTPUT_CSV_HOST"
else
  echo "❌ Error: File could not be retrieved."
fi
