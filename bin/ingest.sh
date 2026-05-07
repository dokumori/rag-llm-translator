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
echo "4) Reset (Wipe existing data)"
echo "----------------------------------------------------------------"
read -p "Choice [1-4]: " choice

case $choice in
  1) FLAGS="" ;;
  2) FLAGS="--glossary-only" ;;
  3) FLAGS="--tm-only" ;;
  4) ;; # FLAGS is set below after reset scope is chosen
  *) echo "Invalid choice"; exit 1 ;;
esac

# 5. For reset, ask what to delete and query languages from the vector DB
if [ "$choice" -eq 4 ]; then
  echo "----------------------------------------------------------------"
  echo "What do you want to reset?"
  echo "1) TM only"
  echo "2) Glossary only"
  echo "3) All (TM + Glossary)"
  echo "----------------------------------------------------------------"
  read -p "Choice [1-3]: " reset_scope
  case $reset_scope in
    1) FLAGS="--reset-only --tm-only"       ; SCOPE_KEY="tm_langs" ;;
    2) FLAGS="--reset-only --glossary-only" ; SCOPE_KEY="glossary_langs" ;;
    3) FLAGS="--reset-only"                 ; SCOPE_KEY="all_langs" ;;
    *) echo "Invalid choice"; exit 1 ;;
  esac

  # Query vector DB for languages via the rag-proxy API.
  echo ""
  echo "🔍 Querying vector DB for ingested languages..."

  LANG_QUERY_CMD="import os, sys; \
from ingest_client import IngestClient; \
url = os.environ.get('RAG_PROXY_URL', 'http://rag-proxy:5000'); \
scope = sys.argv[1] if len(sys.argv) > 1 else 'all_langs'; \
result = IngestClient(url).list_languages(); \
print('\\n'.join(result.get(scope, [])))"

  DB_LANGS=()
  QUERY_FAILED=false
  if DB_LANGS_OUTPUT=$(docker compose exec -T toolbox python3 -c "$LANG_QUERY_CMD" "$SCOPE_KEY" 2>/dev/null); then
    if [ -n "$DB_LANGS_OUTPUT" ]; then
      while IFS= read -r line; do
        [ -n "$line" ] && DB_LANGS+=("$line")
      done <<< "$DB_LANGS_OUTPUT"
    fi
  else
    QUERY_FAILED=true
  fi

  if [ "$QUERY_FAILED" = true ]; then
    echo "⚠️  Could not query languages from the vector DB."
    echo "   Falling back to filesystem-based language list."
    echo "----------------------------------------------------------------"
    echo "Select language to reset:"
    lang_options=("${VALID_LANGS[@]}" "all")
  elif [ ${#DB_LANGS[@]} -eq 0 ]; then
    echo "ℹ️  No languages found in the vector DB for this scope. Nothing to reset."
    exit 0
  else
    echo "📋 Languages in vector DB: ${DB_LANGS[*]}"
    echo "----------------------------------------------------------------"
    echo "Select language to reset:"
    lang_options=("${DB_LANGS[@]}" "all")
  fi

  PS3="Enter the number of your choice: "
  select SELECTED_LANG in "${lang_options[@]}"; do
    if [ -n "$SELECTED_LANG" ]; then
      break
    else
      echo "❌ Invalid option. Please try again."
    fi
  done

  if [ "$SELECTED_LANG" == "all" ]; then
    TARGET_LANGS=("all")
  else
    TARGET_LANGS=("$SELECTED_LANG")
  fi
else
  # Non-reset flow: pick language from filesystem-based list
  echo "----------------------------------------------------------------"
  echo "Select target language for ingestion:"

  lang_options=("${VALID_LANGS[@]}" "all")
  PS3="Enter the number of your choice: "
  select SELECTED_LANG in "${lang_options[@]}"; do
    if [ -n "$SELECTED_LANG" ]; then
      break
    else
      echo "❌ Invalid option. Please try again."
    fi
  done

  if [ "$SELECTED_LANG" == "all" ]; then
    TARGET_LANGS=("${VALID_LANGS[@]}")
  else
    TARGET_LANGS=("$SELECTED_LANG")
  fi
fi

echo "🚀 Launching operation for ${#TARGET_LANGS[@]} language(s)..."
cd "$PROJECT_ROOT"

FAILED_LANGS=()
SUCCESS_LANGS=()
for LANG_CODE in "${TARGET_LANGS[@]}"; do
  echo ""
  echo "================================================================"
  if [ "$choice" -eq 4 ]; then
    echo "🗑️  Resetting: $LANG_CODE"
  else
    echo "📦 Ingesting: $LANG_CODE"
  fi
  echo "================================================================"
  # Use -u to ensure logs appear immediately in the terminal
  if ! docker compose exec toolbox python3 -u /app/src/ingest.py --lang "$LANG_CODE" $FLAGS; then
    echo "⚠️  Operation failed for $LANG_CODE — continuing with remaining languages."
    FAILED_LANGS+=("$LANG_CODE")
  else
    SUCCESS_LANGS+=("$LANG_CODE")
  fi
done

echo ""
echo "================================================================"
if [ "$choice" -eq 4 ]; then
  echo "📊 Reset Summary:"
  if [ ${#SUCCESS_LANGS[@]} -gt 0 ]; then
    echo "✅ Successfully reset: ${SUCCESS_LANGS[*]}"
  fi
else
  echo "📊 Ingestion Summary:"
  if [ ${#SUCCESS_LANGS[@]} -gt 0 ]; then
    echo "✅ Successfully ingested: ${SUCCESS_LANGS[*]}"
  fi
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
