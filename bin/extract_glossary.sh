#!/bin/bash
# bin/extract_glossary.sh
#
# Extracts a draft glossary from the Translation Memory stored in ChromaDB.
# Queries the vector DB for available TM languages, presents an interactive
# language selector, and runs extract_glossary_from_db.py per language.
#
# Usage:
#   bin/extract_glossary.sh   # called from system_menu.sh option G

# Do NOT use set -e: per-language failures should not abort the whole loop.
set +e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

source "$SCRIPT_DIR/common.sh"

if [ -f .env ]; then
    load_env
fi

# ── Colours (inherited from system_menu.sh when called from there) ────────────
BOLD="${BOLD:-\\033[1m}"
YELLOW="${YELLOW:-\\033[33m}"
RESET="${RESET:-\\033[0m}"

echo "----------------------------------------------------------------"
echo "  Extract Glossary from DB"
echo "----------------------------------------------------------------"

# ── Step 1: Stack health check ────────────────────────────────────────────────
PROXY_STATUS=$(docker inspect --format='{{.State.Health.Status}}' rag-proxy 2>/dev/null || echo "not_found")
if [ "$PROXY_STATUS" != "healthy" ]; then
    echo ""
    echo -e "  ${YELLOW}⚠️  Docker stack is not running or rag-proxy is unhealthy.${RESET}"
    echo "     Start with: docker compose up -d"
    exit 1
fi

# ── Step 2: Query the vector DB for TM languages via IngestClient ─────────────
echo "🔍 Querying vector DB for languages with TM data..."

LANG_QUERY_CMD="import os, sys; \
from ingest_client import IngestClient; \
url = os.environ.get('RAG_PROXY_URL', 'http://rag-proxy:5000'); \
result = IngestClient(url).list_languages(); \
print('\n'.join(result.get('tm_langs', [])))"

TM_LANGS=()
QUERY_FAILED=false
if TM_LANGS_OUTPUT=$(docker compose exec -T toolbox python3 -c "$LANG_QUERY_CMD" 2>/dev/null); then
    if [ -n "$TM_LANGS_OUTPUT" ]; then
        while IFS= read -r line; do
            [ -n "$line" ] && TM_LANGS+=("$line")
        done <<< "$TM_LANGS_OUTPUT"
    fi
else
    QUERY_FAILED=true
fi

# ── Step 3: No TM data → inform user and exit ─────────────────────────────────
if [ "$QUERY_FAILED" = true ]; then
    echo ""
    echo -e "  ${YELLOW}⚠️  Could not reach the vector DB. Is the stack running?${RESET}"
    echo "     Check logs: docker compose logs rag-proxy --tail=20"
    exit 1
fi

if [ ${#TM_LANGS[@]} -eq 0 ]; then
    echo ""
    echo -e "  ${YELLOW}⚠️  No Translation Memory data found in ChromaDB.${RESET}"
    echo "     You need to ingest a TM for at least one language before"
    echo "     glossary extraction can run."
    echo ""
    echo "     📖 See: docs/4_glossary_extraction.md"
    echo "         and: README.md §3 \"Place the files\" → then run [I] Ingest"
    exit 1
fi

echo "📋 TM languages found: ${TM_LANGS[*]}"

# ── Step 4: Language selection ────────────────────────────────────────────────
SELECTED=$(select_language_from_db "glossary extraction" "${TM_LANGS[@]}")

# Guard: Ctrl+D exits the select loop and returns an empty string.
if [ -z "$SELECTED" ]; then
    echo ""
    echo "  ↩️  No language selected. Returning to menu..."
    exit 1
fi

# ── Step 5: Expand "all" to the full language list ────────────────────────────
TARGET_LANGS=()
if [ "$SELECTED" = "all" ]; then
    TARGET_LANGS=("${TM_LANGS[@]}")
    echo "🌐 Extracting glossary for ALL languages: ${TARGET_LANGS[*]}"
else
    TARGET_LANGS=("$SELECTED")
    echo "🌐 Extracting glossary for: $SELECTED"
fi

# ── Step 6: Interrupt handler for the extraction loop ────────────────────────
_INTERRUPTED=0
_handle_extract_interrupt() {
    stty sane 2>/dev/null || true
    echo ""
    echo "⚠️  Extraction interrupted! Returning to menu..."
    echo "   Note: any already-completed language files are still available."
    _INTERRUPTED=1
    exit 130
}
trap '_handle_extract_interrupt' INT TERM

# ── Step 7: Per-language extraction loop ─────────────────────────────────────
echo "----------------------------------------------------------------"

FAILED_LANGS=()
SUCCESS_LANGS=()

for LANG_CODE in "${TARGET_LANGS[@]}"; do
    echo ""
    echo "================================================================"
    echo "📄 Extracting glossary: $LANG_CODE"
    echo "================================================================"

    _dc_rc=0
    docker compose exec toolbox python3 -u \
        /app/src/extract_glossary_from_db.py --lang "$LANG_CODE" \
        || _dc_rc=$?

    # Detect signal-death converted to exit 130 by docker
    if [ "$_dc_rc" -eq 130 ] && [ "$_INTERRUPTED" -eq 0 ]; then
        _handle_extract_interrupt
    fi

    if [ "$_dc_rc" -eq 0 ]; then
        SUCCESS_LANGS+=("$LANG_CODE")
    else
        echo "⚠️  Extraction failed for $LANG_CODE — continuing with remaining languages."
        FAILED_LANGS+=("$LANG_CODE")
    fi
done

# ── Step 8: Summary ───────────────────────────────────────────────────────────
echo ""
echo "================================================================"
echo "📊 Glossary Extraction Summary:"
if [ ${#SUCCESS_LANGS[@]} -gt 0 ]; then
    echo "  ✅ Succeeded: ${SUCCESS_LANGS[*]}"
fi
if [ ${#FAILED_LANGS[@]} -gt 0 ]; then
    echo "  ❌ Failed:    ${FAILED_LANGS[*]}"
fi
echo ""
echo "  📁 Output files are in: ./data/rag-analysis/"
for lang in "${SUCCESS_LANGS[@]}"; do
    echo "     • data/rag-analysis/db_derived_glossary_${lang}.csv"
done
echo "================================================================"

if [ ${#FAILED_LANGS[@]} -gt 0 ]; then
    exit 1
fi
