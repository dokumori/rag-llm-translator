#!/bin/bash
# bin/ingest.sh

# The script ingests the glossary and TM files into ChromaDB
# It automatically discovers and ingests ALL language subdirectories
# found under data/tm_source/.

set -e

# Calculate project root
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Source shared helpers
source "$SCRIPT_DIR/common.sh"

echo "🔍 Checking Ingestion Environment..."
echo "📂 Project Root: $PROJECT_ROOT"

# 1. Discover available languages
LANGS=()
while IFS= read -r l; do
  [ -n "$l" ] && LANGS+=("$l")
done < <(discover_lang_dirs "$TM_SOURCE_ROOT")

if [ ${#LANGS[@]} -eq 0 ]; then
  echo "❌ Error: No language subdirectories found in '$TM_SOURCE_ROOT'."
  echo "   Expected structure: $TM_SOURCE_ROOT/{langcode}/ (e.g. $TM_SOURCE_ROOT/ja/)"
  exit 1
fi

echo "🌐 Found ${#LANGS[@]} language(s): ${LANGS[*]}"

# 2. Verify Data Volumes (per-language checks)
VALID_LANGS=()
SKIPPED_LANGS=()
for LANG_CODE in "${LANGS[@]}"; do
  LANG_TM_DIR=$(tm_source_dir "$LANG_CODE")

  # Check for multiple CSV files (Single Glossary Rule)
  csv_count=$(find "$LANG_TM_DIR" -maxdepth 1 -name "*.csv" | wc -l | tr -d ' ')
  if [ "$csv_count" -gt 1 ]; then
    echo "❌ Error: Multiple CSV files found in '$LANG_TM_DIR'."
    echo "   Please ensure only ONE glossary CSV exists per language."
    find "$LANG_TM_DIR" -maxdepth 1 -name "*.csv"
    exit 1
  fi

  po_count=$(find "$LANG_TM_DIR" -maxdepth 1 -name "*.po" -o -name "*.PO" | wc -l | tr -d ' ')
  if [ "$csv_count" -eq 0 ] && [ "$po_count" -eq 0 ]; then
    echo "⚠️  Warning: No .po or .csv files found in $LANG_TM_DIR. ($LANG_CODE will be skipped)"
    SKIPPED_LANGS+=("$LANG_CODE")
  else
    VALID_LANGS+=("$LANG_CODE")
  fi
done

if [ ${#VALID_LANGS[@]} -eq 0 ]; then
  echo "❌ Error: No valid files (.po or .csv) found in any language directory."
  exit 1
fi

# 3. Check Connectivity using the Chroma Library
echo "🔌 Checking ChromaDB connectivity..."

CHECK_CMD="import chromadb, os; \
host = os.environ.get('CHROMA_HOST', 'localhost'); \
port = int(os.environ.get('CHROMA_PORT', 8000)); \
print(f'   Target: {host}:{port}'); \
print(f'   Heartbeat: {chromadb.HttpClient(host=host, port=port).heartbeat()}')"

if ! docker compose exec toolbox python3 -c "$CHECK_CMD"; then
  echo ""
  echo "❌ Error: Connectivity check failed."
  echo "   (See the Python error traceback above for details)"
  exit 1
fi

echo "✅ Environment Ready."

# 4. Prompt for Action
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

# 5. Loop over all languages and ingest
echo "🚀 Launching Ingestion for ${#VALID_LANGS[@]} language(s)..."
cd "$PROJECT_ROOT"

FAILED_LANGS=()
SUCCESS_LANGS=()
for LANG_CODE in "${VALID_LANGS[@]}"; do
  echo ""
  echo "================================================================"
  echo "📦 Ingesting: $LANG_CODE"
  echo "================================================================"
  # Use -u to ensure logs appear immediately in the terminal
  if ! docker compose exec toolbox python3 -u /app/src/ingest.py --lang "$LANG_CODE" $FLAGS; then
    echo "⚠️  Ingestion failed for $LANG_CODE — continuing with remaining languages."
    FAILED_LANGS+=("$LANG_CODE")
  else
    SUCCESS_LANGS+=("$LANG_CODE")
  fi
done

echo ""
echo "================================================================"
echo "📊 Ingestion Summary:"
if [ ${#SUCCESS_LANGS[@]} -gt 0 ]; then
  echo "✅ Successfully ingested: ${SUCCESS_LANGS[*]}"
fi

if [ ${#SKIPPED_LANGS[@]} -gt 0 ]; then
  echo "⏭️  Skipped (no .po or .csv files found): ${SKIPPED_LANGS[*]}"
fi

if [ ${#FAILED_LANGS[@]} -gt 0 ]; then
  echo "❌ Failed (script error or invalid content): ${FAILED_LANGS[*]}"
fi
echo "================================================================"

if [ ${#FAILED_LANGS[@]} -gt 0 ]; then
  exit 1
fi
