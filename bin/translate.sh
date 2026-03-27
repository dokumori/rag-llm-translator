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

MODELS_JSON="config/models.json"
# Host paths for metadata check
INPUT_HOST_DIR="data/translations/input"
OUTPUT_HOST_DIR="data/translations/output"
REQUIRED_LANG_STR="\"Language: ${TARGET_LANG}\\\n\""

# 1. Model Selection Menu
menu_options=()
while IFS= read -r line; do
  menu_options+=("$line")
done < <(python3 -c "import json; [print(m['name']) for m in json.load(open('$MODELS_JSON'))['models']]")
PS3="Enter the number of your choice: "

select opt in "${menu_options[@]}"
do
  if [ -n "$opt" ]; then
    SELECTED_MODEL=$(python3 -c "import json; m = [m for m in json.load(open('$MODELS_JSON'))['models'] if m['name'] == '$opt'][0]; print(m['id'])")
    IS_DRY_RUN=$(python3 -c "import json; m = [m for m in json.load(open('$MODELS_JSON'))['models'] if m['name'] == '$opt'][0]; print(str(m['is_dry_run']).lower())")
    break
  else
    echo "❌ Invalid option. Please try again."
  fi
done

echo ""
if [ "$IS_DRY_RUN" = "true" ]; then
  echo "🔬 DRY RUN MODE: Using $SELECTED_MODEL"
else
  echo "🚀 LIVE RUN: Using $SELECTED_MODEL"
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

# 3. Output Directory Cleanup
if ls "${OUTPUT_HOST_DIR}"/*.po 1> /dev/null 2>&1; then
  echo "⚠️  WARNING: Output directory contains existing files."
  read -p "   Overwrite them? (y/N): " confirm
  if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "❌ Operation cancelled."
    exit 1
  fi
  # Use toolbox to clean purely to avoid host permission issues
  docker compose exec toolbox sh -c 'rm -f /app/po/output/**/*.po'
fi

# 4. Execute Modular Translation Runner
echo "📦 Starting Modular Translation Runner..."
# Note: The runner now handles the recursion and temp isolation internally.
# We point to the container's mount points: /app/po/input and /app/po/output
docker compose exec \
  toolbox python3 -u /app/src/translate_runner.py \
  --model "$SELECTED_MODEL" \
  --input "/app/po/input" \
  --output "/app/po/output" \
  $SKIP_RAG_FLAG

# 5. Post-Processing
echo "✨ Running Post-Process..."
docker compose exec toolbox python3 /app/src/post_process.py /app/po/output

echo "----------------------------------------------------------------"
echo "✅ Translation Workflow Complete!"
echo "----------------------------------------------------------------"
