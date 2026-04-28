#!/bin/bash
# bin/eval_quality.sh
# Executes the LLM-as-a-Judge Evaluation Pipeline

# Load environment variables
if [ -f .env ]; then
  export $(grep -v '^#' .env | grep -vE '^(UID|GID)' | xargs)
fi

set -e

# Source shared helpers
source "$(dirname "$0")/common.sh"

echo "----------------------------------------------------------------"
echo "RAG LLM Translation Quality Evaluation (LLM-as-a-Judge)"
echo "----------------------------------------------------------------"

# Ensure we are running from project root
cd "$(dirname "$0")/.."

MODELS_JSON="config/models/models.json"
CUSTOM_MODELS_JSON="config/models/custom/models.json"  # (Optional) override file

# Safety check for required system models
if [ ! -f "$MODELS_JSON" ]; then
  echo "❌ Error: System models configuration not found at $MODELS_JSON"
  echo "   Please ensure you are running this from the project root."
  exit 1
fi

# Language Selection
TARGET_LANG=$(select_language "evaluation" "${TRANSLATIONS_ROOT}/eval" ".po")
if [ -z "$TARGET_LANG" ]; then
  echo "❌ No language selected or available. Exiting."
  exit 1
fi
echo "🌐 Target language: $TARGET_LANG"

WITH_RAG_DIR=$(eval_dir "$TARGET_LANG")/with_rag
WITHOUT_RAG_DIR=$(eval_dir "$TARGET_LANG")/without_rag

# Helper: load models with custom override support
load_merged_models() {
  python3 -c "
import json, os
base = json.load(open('$MODELS_JSON')).get('models', [])
custom_path = '$CUSTOM_MODELS_JSON'
if custom_path and os.path.exists(custom_path):
    custom = json.load(open(custom_path)).get('models', [])
    dry_run = next((m for m in custom if m.get('is_dry_run')), next((m for m in base if m.get('is_dry_run')), None))
    # Ensure dry run model is always at the end
    models = [m for m in custom if not m.get('is_dry_run')] + ([dry_run] if dry_run else [])
else:
    # Move any dry run model in base to the end
    models = [m for m in base if not m.get('is_dry_run')] + [m for m in base if m.get('is_dry_run')]

for m in models:
    # Add (dry run) suffix to name if missing and it is a dry run model
    if m.get('is_dry_run') and '(dry run)' not in m.get('name', '').lower():
        m['name'] = f\"{m['name']} (dry run)\"
    print(json.dumps(m))
"
}

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
echo "Select the Judge Model:"
menu_options=()
while IFS= read -r line; do
  menu_options+=("$line")
done < <(load_merged_models | python3 -c "import sys, json; [print(json.loads(l)['name']) for l in sys.stdin]")
PS3="Enter the number of your choice (Judge Model): "

select opt in "${menu_options[@]}"
do
  if [ -n "$opt" ]; then
    SELECTED_MODEL=$(load_merged_models | python3 -c "import sys, json; [print(json.loads(l)['id']) for l in sys.stdin if json.loads(l)['name'] == '$opt']" | head -1)
    IS_DRY_RUN=$(load_merged_models | python3 -c "import sys, json; [print(str(json.loads(l)['is_dry_run']).lower()) for l in sys.stdin if json.loads(l)['name'] == '$opt']" | head -1)
    break
  else
    echo "❌ Invalid option. Please try again."
  fi
done

echo ""
if [ "$IS_DRY_RUN" = "true" ]; then
  echo "⚖️  JUDGE MODEL: Dry Run Mode"
else
  echo "⚖️  JUDGE MODEL: $opt"
fi
echo "----------------------------------------------------------------"

# 2. Limit Selection & Statistical Sampling

# Helper Python script to compute total overlapping pairs and Cochran's formula
OVERLAPPING_COUNT=$(docker compose exec -T toolbox python3 -c "
import os, glob
try:
    import polib
except ImportError:
    print('0')
    exit(0)
def load_po_keys(directory):
    keys = set()
    for file_path in glob.glob(os.path.join(directory, '**/*.po'), recursive=True):
        try:
            po = polib.pofile(file_path)
            for entry in po:
                if entry.msgid and entry.msgstr:
                    keys.add(entry.msgid)
        except:
            pass
    return keys

with_rag = load_po_keys('/app/po/eval/$TARGET_LANG/with_rag')
without_rag = load_po_keys('/app/po/eval/$TARGET_LANG/without_rag')
print(len(with_rag.intersection(without_rag)))
")

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

echo "----------------------------------------------------------------"
echo "🚀 Executing Blind Test Evaluation via toolbox..."
echo "----------------------------------------------------------------"

docker compose exec \
  toolbox python3 -u /app/src/evaluate_blind_test.py \
  --model "$SELECTED_MODEL" \
  --with-rag-dir "/app/po/eval/$TARGET_LANG/with_rag" \
  --without-rag-dir "/app/po/eval/$TARGET_LANG/without_rag" \
  --limit "$FINAL_LIMIT"

echo "----------------------------------------------------------------"
echo "✅ Evaluation Workflow Complete!"
echo "----------------------------------------------------------------"
