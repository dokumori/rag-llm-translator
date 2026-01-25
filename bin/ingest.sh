#!/bin/bash
# bin/ingest.sh

# The script ingests the glossary and TM files into ChromaDB

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

# Check for multiple CSV files (Single Glossary Rule)
csv_count=$(find "$PROJECT_ROOT/data/tm_source" -maxdepth 1 -name "*.csv" | wc -l)
if [ "$csv_count" -gt 1 ]; then
  echo "❌ Error: Multiple CSV files found in '$PROJECT_ROOT/data/tm_source'."
  echo "   Please ensure only ONE glossary CSV exists."
  find "$PROJECT_ROOT/data/tm_source" -maxdepth 1 -name "*.csv"
  exit 1
fi

if [ "$csv_count" -eq 0 ]; then
  echo "⚠️  Warning: No glossary CSV found in $PROJECT_ROOT/data/tm_source. (Glossary ingestion will be skipped)"
fi

# 2. Check Connectivity using the Chroma Library
echo "🔌 Checking ChromaDB connectivity..."

# Uses environment variables and prints status to stdout
CHECK_CMD="import chromadb, os; \
host = os.environ.get('CHROMA_HOST', 'localhost'); \
port = int(os.environ.get('CHROMA_PORT', 8000)); \
print(f'   Target: {host}:{port}'); \
print(f'   Heartbeat: {chromadb.HttpClient(host=host, port=port).heartbeat()}')"

# See the actual error if it fails
if ! docker compose exec toolbox python3 -c "$CHECK_CMD"; then
  echo ""
  echo "❌ Error: Connectivity check failed."
  echo "   (See the Python error traceback above for details)"
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
