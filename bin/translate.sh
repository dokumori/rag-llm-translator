#!/bin/bash
# bin/translate.sh

# Executes the translation pipeline

set -e

# Source shared helpers and load .env safely
source "$(dirname "$0")/common.sh"
source "$(dirname "$0")/lib/translate_helpers.sh"
load_env

# ---------------------------------------------------------------------------
# Interrupt handling — Ctrl+C kills the in-container process but keeps
# Docker containers running so the user can immediately retry.
# ---------------------------------------------------------------------------
_INTERRUPTED=0
_handle_interrupt() {
  stty sane 2>/dev/null || true   # restore terminal if docker's PTY left it in raw mode
  echo ""
  echo "⚠️  Translation interrupted!"
  # No kill needed — Python re-raises SIGINT as a real signal death,
  # so the container process is already gone by the time we get here.
  _INTERRUPTED=1
  echo "✅ Translation process stopped. Containers are still running."
  echo "   To fully stop containers, run: docker compose stop"
  exit 130
}
trap '_handle_interrupt' INT TERM

echo "----------------------------------------------------------------"
echo "RAG LLM Translation System"
echo "----------------------------------------------------------------"

# Ensure we are running from project root
cd "$(dirname "$0")/.."

MODELS_YAML="config/models.yaml"

# Safety check for required models config
if [ ! -f "$MODELS_YAML" ]; then
  echo "❌ Error: Models configuration not found at $MODELS_YAML"
  echo "   Run bin/setup.sh to generate it, or copy config/models.example.yaml to config/models.yaml."
  exit 1
fi

# ---------------------------------------------------------------------------
# _is_remote_model — returns 0 if the selected model incurs API costs.
# Dry-run and local (ollama) models are excluded.
# ---------------------------------------------------------------------------
_is_remote_model() {
  [ "$IS_DRY_RUN" != "true" ] \
    && [ "$MODEL_PROVIDER" != "ollama" ]
}

# ---------------------------------------------------------------------------
# _select_translation_params — interactive selection of language, model, RAG
# mode, and cost confirmation.
#
# Sets globals: TARGET_LANG, TARGET_LANGS, SELECTED_MODEL, IS_DRY_RUN,
#               MODEL_PROVIDER, SKIP_RAG_ARGS
#
# Returns 0 if the user confirmed and translation should proceed.
# Returns 1 if the user asked to restart the selection from the beginning.
# ---------------------------------------------------------------------------
_select_translation_params() {

  # 1. Language Selection
  if [[ "$1" == -* ]]; then
    TARGET_LANG="${1#-}"
  else
    TARGET_LANG=$(select_language "translation" "${TRANSLATIONS_ROOT}/input" ".po")
  fi

  if [ -z "$TARGET_LANG" ]; then
    echo "❌ No language selected or available. Exiting."
    exit 1
  fi

  if [ "$TARGET_LANG" = "all" ]; then
    echo "🌐 Target languages: ALL available languages"
    TARGET_LANGS=($(list_available_langs "${TRANSLATIONS_ROOT}/input" ".po"))
  else
    echo "🌐 Target language: $TARGET_LANG"
    TARGET_LANGS=("$TARGET_LANG")
  fi

  # Helper: path to shared model config script (runs inside toolbox to avoid host PyYAML dep)
  local MODEL_CONFIG="/app/bin/lib/model_config.py"
  local CONTAINER_MODELS_YAML="/app/config/models.yaml"

  # 2. Model Selection Menu
  local menu_options=()
  while IFS= read -r line; do
    menu_options+=("$line")
  done < <(docker compose exec -T toolbox python3 "$MODEL_CONFIG" list --models "$CONTAINER_MODELS_YAML" --format names)
  PS3="Enter the number of your choice: "

  local opt
  select opt in "${menu_options[@]}"
  do
    if [ -n "$opt" ]; then
      local LOOKUP_OUTPUT
      LOOKUP_OUTPUT=$(docker compose exec -T toolbox python3 "$MODEL_CONFIG" list --models "$CONTAINER_MODELS_YAML" --format lookup --name "$opt")
      SELECTED_MODEL=$(echo "$LOOKUP_OUTPUT" | sed -n '1p')
      IS_DRY_RUN=$(echo "$LOOKUP_OUTPUT"    | sed -n '2p')
      MODEL_PROVIDER=$(echo "$LOOKUP_OUTPUT" | sed -n '3p')
      break
    else
      echo "❌ Invalid option. Please try again."
    fi
  done

  echo ""
  if [ "$IS_DRY_RUN" = "true" ]; then
    echo "🔬 DRY RUN MODE"
  else
    echo "🚀 LIVE RUN: Using $opt"
  fi

  # 3. RAG Mode Selection
  echo "----------------------------------------------------------------"
  echo "Select Evaluation Mode:"
  local rag_options=("With RAG (Default context injection)" "Without RAG (skip-rag flag)")
  PS3="Enter the number of your choice: "

  local rag_opt
  select rag_opt in "${rag_options[@]}"
  do
    if [ "$REPLY" -eq 1 ]; then
      SKIP_RAG_ARGS=()
      echo "🧠 Mode: WITH RAG"
      break
    elif [ "$REPLY" -eq 2 ]; then
      SKIP_RAG_ARGS=(--skip-rag)
      echo "⏩ Mode: WITHOUT RAG (skip-rag)"
      break
    else
      echo "❌ Invalid option. Please try again."
    fi
  done

  echo "----------------------------------------------------------------"

  # 4. Pre-flight Cost Estimate
  # Only runs for non-dry-run, non-local models.
  # Custom endpoint models are included so users still see the estimate prompt
  # (or a clear message when no pricing data is configured).
  if _is_remote_model; then
    local _est_lang _est_input_dir ESTIMATE_OUTPUT
    local EST_STRINGS EST_BATCHES EST_COST_LOW EST_COST_HIGH HAS_PRICING
    for _est_lang in "${TARGET_LANGS[@]}"; do
      _est_input_dir=$(input_dir "$_est_lang")
      if [ -d "$_est_input_dir" ]; then
        ESTIMATE_OUTPUT=$(docker compose exec -T toolbox python3 -u /app/src/estimate_cost.py \
          --input "/app/po/input/$_est_lang" \
          --model "$SELECTED_MODEL" \
          --target-lang "$_est_lang" \
          --bulk-size "${BULK_SIZE:-15}" \
          "${SKIP_RAG_ARGS[@]}" \
          2>/dev/null) || true

        if [ -n "$ESTIMATE_OUTPUT" ]; then
          EST_STRINGS=$(echo "$ESTIMATE_OUTPUT" | grep '^STRINGS='    | cut -d= -f2)
          EST_BATCHES=$(echo "$ESTIMATE_OUTPUT" | grep '^BATCHES='    | cut -d= -f2)
          EST_COST_LOW=$(echo "$ESTIMATE_OUTPUT" | grep '^COST_LOW='  | cut -d= -f2)
          EST_COST_HIGH=$(echo "$ESTIMATE_OUTPUT" | grep '^COST_HIGH=' | cut -d= -f2)
          HAS_PRICING=$(echo "$ESTIMATE_OUTPUT"  | grep '^HAS_PRICING=' | cut -d= -f2)

          echo "----------------------------------------------------------------"
          echo "📊 Cost Estimate — $opt ($EST_STRINGS strings, $_est_lang)"
          echo "   Strings to translate  : $EST_STRINGS"
          echo "   Batches (~${BULK_SIZE:-15} strings/batch) : $EST_BATCHES"
          if [ "$HAS_PRICING" = "true" ]; then
            echo "   Estimated cost (range): \$$EST_COST_LOW – \$$EST_COST_HIGH"
          else
            echo "   Estimated cost        : N/A"
            echo "   ⚠️  No pricing information found for '$SELECTED_MODEL' in config/models.yaml."
            echo "      Cost estimate cannot be displayed. To enable it, add a 'pricing' block"
            echo "      to this model's entry in config/models.yaml, e.g.:"
            echo "        pricing:"
            echo "          prompt_per_1k_tokens: 0.001"
            echo "          completion_per_1k_tokens: 0.005"
          fi
          if [ "$HAS_PRICING" = "true" ] && [ ${#SKIP_RAG_ARGS[@]} -eq 0 ]; then
            echo "   ⓘ  Actual cost will vary depending on the volume of RAG context"
            echo "      injected per batch (size of glossary/TM)."
          fi
          echo "----------------------------------------------------------------"
        fi
      fi
    done

    local _est_confirm
    read -rp "Proceed with translation? [Y/n/q — q to quit]: " _est_confirm
    _est_confirm="${_est_confirm:-Y}"
    if [[ "$_est_confirm" =~ ^[Qq]$ ]]; then
      echo "❌ Translation cancelled."
      exit 0
    elif [[ ! "$_est_confirm" =~ ^[Yy]$ ]]; then
      echo "↩️  Restarting selection..."
      echo "----------------------------------------------------------------"
      return 1   # signal: restart the selection loop
    fi
  fi

  return 0   # confirmed — proceed to translation
}

# Steps 1–4 are wrapped in a loop so the user can restart language,
# model, and RAG selection if they decline the cost estimate.
while ! _select_translation_params "$@"; do :; done

# 5. Metadata Validation (Pre-flight check)
for LANG_ITER in "${TARGET_LANGS[@]}"; do
  echo "----------------------------------------------------------------"
  echo "⚙️ Processing language: $LANG_ITER"
  echo "----------------------------------------------------------------"
  
  TARGET_LANG="$LANG_ITER"
  INPUT_HOST_DIR=$(input_dir "$TARGET_LANG")
  OUTPUT_HOST_DIR=$(output_dir "$TARGET_LANG")
  REQUIRED_LANG_STR="\"Language: ${TARGET_LANG}\\n\""

  # Ensure output directory exists
  mkdir -p "$OUTPUT_HOST_DIR"

  echo "🔍 Validating .po metadata in $INPUT_HOST_DIR..."
# Note: This runs on the host to ensure headers are present before container processing
for po_file in "$INPUT_HOST_DIR"/*.po; do
  [ -e "$po_file" ] || continue
  python3 - "$po_file" "$REQUIRED_LANG_STR" <<'EOF'
import sys, re, os

# Read the target .po file into memory for header manipulation
po_file, lang_str = sys.argv[1], sys.argv[2]
with open(po_file, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Correct langcode already present — nothing to do.
if lang_str in content:
    sys.exit(0)

# 2. A *different* Language: line exists — replace it.
if re.search(r'^"Language: [^\\]+\\n"', content, re.MULTILINE):
    new_content = re.sub(
        r'^"Language: [^\\]+\\n"', # Pattern to find
        lambda m: lang_str,        # Use lambda to avoid re.sub backslash processing
        content,                   # Source text
        count=1,                   # Only replace the first occurrence
        flags=re.MULTILINE,        # Treat each line as a start
    )
    with open(po_file, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f"Replaced Language header in {os.path.basename(po_file)} with {lang_str.strip()}")
    sys.exit(0)

# 3. No `Language:` line at all — insert into the header block.
print(f"Adding missing language header to {os.path.basename(po_file)}...")
pattern = r'((?:^"[^\n]*\\n"\n)+)(\n)'
new_content = re.sub(
    pattern,
    lambda m: m.group(1) + lang_str + '\n' + m.group(2),
    content,
    count=1,
    flags=re.MULTILINE,
)
with open(po_file, 'w', encoding='utf-8') as f:
    f.write(new_content)
EOF
done

# 6. Prepare Naming Metadata
MODEL_SLUG=$(_compute_model_slug "$SELECTED_MODEL" "$IS_DRY_RUN")

if [ ${#SKIP_RAG_ARGS[@]} -gt 0 ]; then
  RAG_MODE="norag"
else
  RAG_MODE="rag"
fi

# 7. Pre-flight Check for conflicting files
echo "🔍 Checking for output conflicts..."
CONFLICTS_FOUND=0
while read -r input_file; do
  REL_PATH="${input_file#$INPUT_HOST_DIR/}"
  if [ -f "${OUTPUT_HOST_DIR}/${REL_PATH}" ]; then
    echo "   ❌ Conflict found: ${OUTPUT_HOST_DIR}/${REL_PATH} already exists."
    CONFLICTS_FOUND=1
  fi
done < <(find "$INPUT_HOST_DIR" -maxdepth 1 -type f -name "*.po" 2>/dev/null || true)

if [ "$CONFLICTS_FOUND" -eq 1 ]; then
  echo "❌ Error: Found existing .po files in the output directory with the same exact names as the input files."
  echo "   Please clear or rename these files before running the translation."
  exit 1
fi

TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")

# 8. Execute Modular Translation Runner
echo "📦 Starting Modular Translation Runner..."
_dc_rc=0
docker compose exec \
  toolbox python3 -u /app/src/translate_runner.py \
  --model "$SELECTED_MODEL" \
  --input "/app/po/input/$TARGET_LANG" \
  --output "/app/po/output/$TARGET_LANG" \
  --target-lang "$TARGET_LANG" \
  --model-slug "$MODEL_SLUG" \
  --rag-mode "$RAG_MODE" \
  --timestamp "$TIMESTAMP" \
  "${SKIP_RAG_ARGS[@]}" \
  || _dc_rc=$?

# Fallback: if docker converted the signal death to a normal exit 130,
# bash's WCE discards the pending SIGINT and the INT trap never fires.
# Detect that case here and run the handler explicitly.
if [ "$_dc_rc" -eq 130 ] && [ "$_INTERRUPTED" -eq 0 ]; then
  _handle_interrupt
fi
# Non-interrupt failure — let set -e handle it
[ "$_dc_rc" -eq 0 ] || [ "$_dc_rc" -eq 130 ] || exit "$_dc_rc"

# 9. Post-Processing
  echo "✨ Running Post-Process..."
  _post_process_lang "/app/po/output/$TARGET_LANG" "$TARGET_LANG"

done

echo "----------------------------------------------------------------"
if [ "$_INTERRUPTED" -eq 1 ]; then
  echo "⚠️  Translation was interrupted — workflow did not complete."
  echo "   Containers are still running. Run translate.sh again to retry."
else
  echo "✅ Translation Workflow Complete!"
fi
echo "----------------------------------------------------------------"
