#!/bin/bash
# bin/translate.sh

# Executes the translation pipeline

# Load environment variables
if [ -f .env ]; then
  export $(grep -v '^#' .env | grep -vE '^(UID|GID)' | xargs)
fi

# Default to 'ja' if not set in .env
TARGET_LANG=${TARGET_LANG:-ja}

set -e

echo "----------------------------------------------------------------"
echo "RAG LLM Translation System"
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

# Host paths for metadata check
INPUT_HOST_DIR="data/translations/input"
OUTPUT_HOST_DIR="data/translations/output"
REQUIRED_LANG_STR="\"Language: ${TARGET_LANG}\\\n\""

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

# 1. Model Selection Menu
menu_options=()
while IFS= read -r line; do
  menu_options+=("$line")
done < <(load_merged_models | python3 -c "import sys, json; [print(json.loads(l)['name']) for l in sys.stdin]")
PS3="Enter the number of your choice: "

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
  echo "🔬 DRY RUN MODE"
else
  echo "🚀 LIVE RUN: Using $opt"
fi

# 1.5 RAG Mode Selection
echo "----------------------------------------------------------------"
echo "Select Evaluation Mode:"
rag_options=("With RAG (Default context injection)" "Without RAG (skip-rag flag)")
PS3="Enter the number of your choice: "

select rag_opt in "${rag_options[@]}"
do
  if [ "$REPLY" -eq 1 ]; then
    SKIP_RAG_FLAG=""
    echo "🧠 Mode: WITH RAG"
    break
  elif [ "$REPLY" -eq 2 ]; then
    SKIP_RAG_FLAG="--skip-rag"
    echo "⏩ Mode: WITHOUT RAG (skip-rag)"
    break
  else
    echo "❌ Invalid option. Please try again."
  fi
done

echo "----------------------------------------------------------------"

# 2. Metadata Validation (Pre-flight check)
echo "🔍 Validating .po metadata in $INPUT_HOST_DIR..."
# Note: This runs on the host to ensure headers are present before container processing
for po_file in "$INPUT_HOST_DIR"/*.po; do
  [ -e "$po_file" ] || continue
  if ! grep -qi "Language: ${TARGET_LANG}" "$po_file"; then
    echo "📝 Adding missing language header to $(basename "$po_file")..."
    { printf "%s\n" "$REQUIRED_LANG_STR"; cat "$po_file"; } > "${po_file}.tmp" && mv "${po_file}.tmp" "$po_file"
  fi
done

# 3. Prepare Naming Metadata
if [ "$IS_DRY_RUN" = "true" ]; then
  MODEL_SLUG="dry-run"
else
  # Convert to lowercase and replace spaces with dashes safely
  MODEL_SLUG=$(echo "$SELECTED_MODEL" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/-\{2,\}/-/g' | sed 's/^-//;s/-$//')
fi

if [ -n "$SKIP_RAG_FLAG" ]; then
  RAG_MODE="norag"
else
  RAG_MODE="rag"
fi

# 3.5 Pre-flight Check for conflicting files
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

# 4. Execute Modular Translation Runner
echo "📦 Starting Modular Translation Runner..."
# Note: The runner now handles the recursion and temp isolation internally.
# We point to the container's mount points: /app/po/input and /app/po/output
docker compose exec \
  toolbox python3 -u /app/src/translate_runner.py \
  --model "$SELECTED_MODEL" \
  --input "/app/po/input" \
  --output "/app/po/output" \
  --model-slug "$MODEL_SLUG" \
  --rag-mode "$RAG_MODE" \
  --timestamp "$TIMESTAMP" \
  $SKIP_RAG_FLAG

# 5. Post-Processing
echo "✨ Running Post-Process..."
docker compose exec toolbox python3 /app/src/post_process.py /app/po/output



echo "----------------------------------------------------------------"
echo "✅ Translation Workflow Complete!"
echo "----------------------------------------------------------------"
