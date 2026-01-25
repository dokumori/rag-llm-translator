#!/bin/bash
set -e

# Define paths
LOG_FILE_HOST="data/logs/translation.jsonl"
LOG_FILE_CONTAINER="/app/data/logs/translation.jsonl"
ANALYSER_SCRIPT="/app/src/analyse_logs.py"
MISSES_CSV_HOST="data/rag-analysis/near_misses.csv"
MATCHES_CSV_HOST="data/rag-analysis/matches.csv"
MISSES_CSV_CONTAINER="/app/data/rag-analysis/near_misses.csv"
MATCHES_CSV_CONTAINER="/app/data/rag-analysis/matches.csv"

# 1. Clean up OLD reports so we don't get false positives
rm -f "$MISSES_CSV_HOST" "$MATCHES_CSV_HOST"

# 2. Capture Logs (Disable colour codes to fix parsing issues)
echo "📊 Capturing logs from rag-proxy..."
mkdir -p data/logs
docker compose logs --no-color --no-log-prefix rag-proxy > "$LOG_FILE_HOST"

# 3. Check if logs are empty
if [ ! -s "$LOG_FILE_HOST" ]; then
  echo "❌ Error: Log file is empty. No traffic captured."
  exit 1
fi

# 4. Send logs to toolbox
echo "🚚 Sending logs to toolbox container..."
docker compose exec -u 0 toolbox mkdir -p /app/data/logs

# 5. Run Analysis
echo "🚀 Running analysis inside toolbox..."
docker compose exec toolbox python3 "$ANALYSER_SCRIPT" "$LOG_FILE_CONTAINER"

# 6. Retrieve Reports
echo "📥 Retrieving reports..."

# Copy Misses
docker compose cp toolbox:"$MISSES_CSV_CONTAINER" "$MISSES_CSV_HOST" 2>/dev/null || true
if [ -f "$MISSES_CSV_HOST" ]; then
  echo "✅ Saved: $MISSES_CSV_HOST"
else
  echo "ℹ️  No near_misses.csv generated."
fi

# Copy Matches
docker compose cp toolbox:"$MATCHES_CSV_CONTAINER" "$MATCHES_CSV_HOST" 2>/dev/null || true
if [ -f "$MATCHES_CSV_HOST" ]; then
  echo "✅ Saved: $MATCHES_CSV_HOST"
else
  echo "ℹ️  No matches.csv generated."
fi
