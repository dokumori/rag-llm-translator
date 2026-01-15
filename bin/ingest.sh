#!/bin/bash
# bin/check_ingest.sh

# Ingests the glossary and TM files into ChromaDB

set -e

# Calculate project root
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "🔍 Checking Ingestion Environment..."
echo "📂 Project Root: $PROJECT_ROOT"

# 1. Verify Data Volumes
if [ ! -d "$PROJECT_ROOT/data/tm_source" ]; then
  echo "❌ Error: '$PROJECT_ROOT/data/tm_source' directory not found."
  exit 1
fi

if [ ! -f "$PROJECT_ROOT/data/tm_source/glossary.csv" ]; then
  echo "⚠️  Warning: 'glossary.csv' not found in $PROJECT_ROOT/data/tm_source."
fi

# 2. Check Connectivity using the Chroma Library (Syntax-Corrected)
echo "🔌 Checking ChromaDB connectivity..."

# Simplified one-liner: if it crashes, it returns non-zero status
CHECK_CMD="import chromadb; chromadb.HttpClient(host='chroma', port=8000).heartbeat()"

if ! docker compose exec toolbox python3 -c "$CHECK_CMD" > /dev/null 2>&1; then
  echo "❌ Error: Cannot reach ChromaDB. Is the 'chroma' container healthy?"
  echo "   (Checked via: chromadb.HttpClient.heartbeat())"
  exit 1
fi

echo "✅ Environment Ready."

# 3. Prompt for Action
echo "----------------------------------------------------------------"
echo "Select ingestion mode:"
echo "1) Full Ingest (Glossary + TM)"
echo "2) Glossary Only"
echo "3) TM Only"
echo "4) Reset & Full Ingest (Wipe existing data)"
echo "----------------------------------------------------------------"
read -p "Choice [1-4]: " choice

case $choice in
  1) FLAGS="" ;;
  2) FLAGS="--glossary-only" ;;
  3) FLAGS="--tm-only" ;;
  4) FLAGS="--reset" ;;
  *) echo "Invalid choice"; exit 1 ;;
esac

echo "🚀 Launching Ingestion..."
cd "$PROJECT_ROOT"
# Use -u to ensure logs appear immediately in the terminal
docker compose exec toolbox python3 -u /app/src/ingest.py $FLAGS
