#!/bin/bash
# bin/eval_quality.sh
# Executes the LLM-as-a-Judge Evaluation Pipeline
#
# Usage:
#   bin/eval_quality.sh                                          # fully interactive
#   bin/eval_quality.sh --lang fr --model dry-run-dummy --limit all  # fully non-interactive
#
# Options:
#   --lang <code>                    Target language (skips language menu)
#   --model <id>                     Judge model id (machine name, the 'id' field in
#                                    config/models/models.yaml; skips model menu)
#   --limit <N|all|recommended>      Evaluation sample limit (skips limit menu):
#                                      N            evaluate exactly N strings
#                                      all          evaluate every overlapping string
#                                      recommended  use the Cochran statistical sample
#   -h, --help                       Show this help
#
# Any prompt whose value was not provided via a flag remains interactive.
# Invalid flag values terminate the script with an error before any work starts.

set -e

_usage() { sed -n '5,20p' "$0" | sed 's/^# \{0,1\}//'; }

# ---------------------------------------------------------------------------
# Argument parsing — flag values pre-answer the corresponding prompts.
# ---------------------------------------------------------------------------
FLAG_LANG=""
FLAG_MODEL=""
FLAG_LIMIT=""

while [ $# -gt 0 ]; do
  case "$1" in
    --lang)    [ -n "${2:-}" ] || { echo "❌ --lang requires a value"; exit 1; }
               FLAG_LANG="$2"; shift 2 ;;
    --model)   [ -n "${2:-}" ] || { echo "❌ --model requires a value"; exit 1; }
               FLAG_MODEL="$2"; shift 2 ;;
    --limit)   [ -n "${2:-}" ] || { echo "❌ --limit requires a value"; exit 1; }
               FLAG_LIMIT="$2"; shift 2 ;;
    -h|--help) _usage; exit 0 ;;
    *)         echo "❌ Unknown argument: $1"; _usage; exit 1 ;;
  esac
done

# Validate --limit early so bad values fail before any Docker work.
if [ -n "$FLAG_LIMIT" ] && [ "$FLAG_LIMIT" != "all" ] && [ "$FLAG_LIMIT" != "recommended" ] \
   && ! [[ "$FLAG_LIMIT" =~ ^[0-9]+$ ]]; then
  echo "❌ Error: --limit must be a positive number, 'all', or 'recommended' (got '$FLAG_LIMIT')."
  exit 1
fi

# Source shared helpers and load .env safely
source "$(dirname "$0")/common.sh"
load_env

echo "----------------------------------------------------------------"
echo "RAG LLM Translation Quality Evaluation (LLM-as-a-Judge)"
echo "----------------------------------------------------------------"

# Ensure we are running from project root
cd "$(dirname "$0")/.."

MODELS_YAML="config/models/models.yaml"
CONTAINER_MODELS_YAML="/app/config/models/models.yaml"

# Safety check for required models config
if [ ! -f "$MODELS_YAML" ]; then
  echo "❌ Error: Models configuration not found at $MODELS_YAML"
  echo "   Run bin/setup.sh to generate it, or copy config/models/models.example.yaml to config/models/models.yaml."
  exit 1
fi

# Language Selection
if [ -n "$FLAG_LANG" ]; then
  TARGET_LANG="$FLAG_LANG"
  # Validate against languages that actually have evaluation files.
  if ! list_available_langs "${TRANSLATIONS_ROOT}/eval" ".po" | grep -qx "$TARGET_LANG"; then
    echo "❌ Error: no .po evaluation files found for language '$TARGET_LANG' under ${TRANSLATIONS_ROOT}/eval."
    echo "   Available languages:"
    list_available_langs "${TRANSLATIONS_ROOT}/eval" ".po" | sed 's/^/   - /'
    exit 1
  fi
else
  TARGET_LANG=$(select_language "evaluation" "${TRANSLATIONS_ROOT}/eval" ".po")
fi
if [ -z "$TARGET_LANG" ]; then
  echo "❌ No language selected or available. Exiting."
  exit 1
fi
echo "🌐 Target language: $TARGET_LANG"

WITH_RAG_DIR=$(eval_dir "$TARGET_LANG")/with_rag
WITHOUT_RAG_DIR=$(eval_dir "$TARGET_LANG")/without_rag

# Helper: path to shared model config script (runs inside toolbox to avoid host PyYAML dep)
MODEL_CONFIG="/app/bin/lib/model_config.py"


# Ensure directories exist
mkdir -p "$WITH_RAG_DIR"
mkdir -p "$WITHOUT_RAG_DIR"

check_dir() {
  local dir=$1
  local total=0
  local po=0
  for f in "$dir"/*; do
    [ -e "$f" ] || continue
    total=$((total + 1))
    [[ "$f" == *.po ]] && po=$((po + 1))
  done
  echo "$total:$po"
}

STATS_WITH=$(check_dir "$WITH_RAG_DIR")
STATS_WITHOUT=$(check_dir "$WITHOUT_RAG_DIR")

if [ "${STATS_WITH%:*}" -eq 0 ] || [ "${STATS_WITHOUT%:*}" -eq 0 ]; then
  echo "⚠️  WARNING: Evaluation directories are empty!"
  echo "Please run translation workflows to populate these directories first:"
  echo "  - $WITH_RAG_DIR"
  echo "  - $WITHOUT_RAG_DIR"
  echo "Exiting."
  exit 1
fi

if [ "${STATS_WITH%:*}" -ne 1 ] || [ "${STATS_WITHOUT%:*}" -ne 1 ] || [ "${STATS_WITH#*:}" -ne 1 ] || [ "${STATS_WITHOUT#*:}" -ne 1 ]; then
  echo "❌ Error: Each evaluation directory must contain exactly one file, and it must be a .po file."
  echo "Check directories:"
  echo "  - $WITH_RAG_DIR"
  echo "  - $WITHOUT_RAG_DIR"
  exit 1
fi

# 1. Model Selection Menu
# Note: lookup output is "<id>\n<is_dry_run>\n<provider>" — is_dry_run is line 2.
if [ -n "$FLAG_MODEL" ]; then
  opt="$FLAG_MODEL"
  if ! LOOKUP_OUTPUT=$(docker compose exec -T toolbox python3 "$MODEL_CONFIG" list --models "$CONTAINER_MODELS_YAML" --format lookup --name "$opt" </dev/null 2>/dev/null); then
    echo "❌ Error: model '$opt' not found in config/models/models.yaml."
    echo "   Available model ids:"
    docker compose exec -T toolbox python3 "$MODEL_CONFIG" list --models "$CONTAINER_MODELS_YAML" --format ids | sed 's/^/   - /'
    exit 1
  fi
  SELECTED_MODEL=$(echo "$LOOKUP_OUTPUT" | sed -n '1p')
  IS_DRY_RUN=$(echo "$LOOKUP_OUTPUT" | sed -n '2p')
else
  echo "Select the Judge Model:"
  # One round-trip: "id<US>is_dry_run<US>provider<US>name" per model
  # (US = ASCII 0x1f — a non-whitespace IFS so empty fields survive).
  # The menu displays names; parallel arrays keep the id and metadata.
  menu_ids=()
  menu_dry=()
  menu_options=()
  while IFS=$'\x1f' read -r _id _dry _provider _name; do
    menu_ids+=("$_id")
    menu_dry+=("$_dry")
    menu_options+=("$_name")
  done < <(docker compose exec -T toolbox python3 "$MODEL_CONFIG" list --models "$CONTAINER_MODELS_YAML" --format menu </dev/null)
  PS3="Enter the number of your choice (Judge Model): "

  SELECTED_MODEL=""
  select opt in "${menu_options[@]}"
  do
    if [ -n "$opt" ]; then
      SELECTED_MODEL="${menu_ids[$((REPLY - 1))]}"
      IS_DRY_RUN="${menu_dry[$((REPLY - 1))]}"
      break
    else
      echo "❌ Invalid option. Please try again."
    fi
  done

  # Guard: Ctrl+D / EOF exits the select loop without a selection.
  if [ -z "$SELECTED_MODEL" ]; then
    echo "❌ No model selected. Exiting."
    exit 1
  fi
fi

echo ""
if [ "$IS_DRY_RUN" = "true" ]; then
  echo "⚖️  JUDGE MODEL: Dry Run Mode"
else
  echo "⚖️  JUDGE MODEL: $opt"
fi
echo "----------------------------------------------------------------"

# 2. Limit Selection & Statistical Sampling

# Helper Python script to compute total overlapping pairs and Cochran's formula
OVERLAPPING_COUNT=$(docker compose exec -T -e TARGET_LANG="$TARGET_LANG" toolbox python3 -c "
import os, glob
try:
    import polib
except ImportError:
    print('0')
    exit(0)
lang = os.environ['TARGET_LANG']
def load_po_keys(directory):
    keys = set()
    for file_path in glob.glob(os.path.join(directory, '**/*.po'), recursive=True):
        try:
            po = polib.pofile(file_path)
            for entry in po:
                if entry.msgid and entry.msgstr:
                    keys.add(entry.msgid)
        except Exception:
            pass
    return keys

with_rag = load_po_keys(f'/app/po/eval/{lang}/with_rag')
without_rag = load_po_keys(f'/app/po/eval/{lang}/without_rag')
print(len(with_rag.intersection(without_rag)))
" </dev/null)

if [ "$OVERLAPPING_COUNT" -eq 0 ]; then
  echo "❌ Error: Could not find any overlapping translated strings between the two directories."
  echo "Are you sure polib is installed and the directories contain valid .po files?"
  exit 1
fi

# Calculate Cochran's formula locally: n = 384 / (1 + (384/N))
RECOMMENDED_SAMPLE=$(python3 -c "
import math
n0 = 384
N = $OVERLAPPING_COUNT
if N == 0:
    print(0)
else:
    print(math.ceil(n0 / (1 + (n0/N))))
")

echo "📊 Data detected: $OVERLAPPING_COUNT overlapping translated strings."
echo "Statistical Target (95% Conf, 5% Err): $RECOMMENDED_SAMPLE strings."
echo ""
if [ -n "$FLAG_LIMIT" ]; then
  case "$FLAG_LIMIT" in
    all)          FINAL_LIMIT="0";                  echo "Using LIMIT: ALL ($OVERLAPPING_COUNT strings)" ;;
    recommended)  FINAL_LIMIT="$RECOMMENDED_SAMPLE"; echo "Using LIMIT: $RECOMMENDED_SAMPLE (recommended sample)" ;;
    *)            FINAL_LIMIT="$FLAG_LIMIT";         echo "Using LIMIT: $FINAL_LIMIT" ;;
  esac
else
  FINAL_LIMIT=""
  echo "Select Evaluation Sample Limit:"
  limit_options=(
    "Use the Recommended Statistical Sample ($RECOMMENDED_SAMPLE strings)"
    "Custom Limit"
    "Evaluate ALL ($OVERLAPPING_COUNT strings)"
  )
  PS3="Enter the number of your choice: "

  select l_opt in "${limit_options[@]}"
  do
    if [ "$REPLY" -eq 1 ]; then
      FINAL_LIMIT="$RECOMMENDED_SAMPLE"
      echo "Using LIMIT: $RECOMMENDED_SAMPLE"
      break
    elif [ "$REPLY" -eq 2 ]; then
      read -p "Enter custom limit number: " custom_num
      if [[ "$custom_num" =~ ^[0-9]+$ ]]; then
        FINAL_LIMIT="$custom_num"
        echo "Using LIMIT: $FINAL_LIMIT"
        break
      else
        echo "❌ Invalid number. Please try again."
      fi
    elif [ "$REPLY" -eq 3 ]; then
      FINAL_LIMIT="0"
      echo "Using LIMIT: ALL ($OVERLAPPING_COUNT strings)"
      break
    else
      echo "❌ Invalid option. Please try again."
    fi
  done

  # Guard: Ctrl+D / EOF exits the select loop without a selection.
  if [ -z "$FINAL_LIMIT" ]; then
    echo "❌ No sample limit selected. Exiting."
    exit 1
  fi
fi

echo "----------------------------------------------------------------"
echo "🚀 Executing Blind Test Evaluation via toolbox..."
echo "----------------------------------------------------------------"

docker compose exec \
  toolbox python3 -u /app/src/evaluate_blind_test.py \
  --model "$SELECTED_MODEL" \
  --with-rag-dir "/app/po/eval/$TARGET_LANG/with_rag" \
  --without-rag-dir "/app/po/eval/$TARGET_LANG/without_rag" \
  --limit "$FINAL_LIMIT" \
  --lang "$TARGET_LANG"

echo "----------------------------------------------------------------"
echo "✅ Evaluation Workflow Complete!"
echo "----------------------------------------------------------------"
