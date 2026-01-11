#!/bin/bash
# bin/translate.sh

# Load environment variables
if [ -f .env ]; then
  export $(grep -v '^#' .env | grep -vE '^(UID|GID)' | xargs)
fi

# Default to 'ja' if not set in .env
TARGET_LANG=${TARGET_LANG:-ja}

set -e

echo "----------------------------------------------------------------"
echo "Please select the LLM model to use:"
echo "----------------------------------------------------------------"

MODELS_JSON="config/models.json"
INPUT_HOST_DIR="data/translations/input"
OUTPUT_HOST_DIR="data/translations/output"
# The exact string required by Gettext/gpt-po-translator
REQUIRED_LANG_STR="\"Language: ${TARGET_LANG}\\\n\""

# Parse JSON names for the menu
menu_options=()
while IFS= read -r line; do
  menu_options+=("$line")
done < <(python3 -c "import json; [print(m['name']) for m in json.load(open('$MODELS_JSON'))['models']]")
PS3="Enter the number of your choice: "

select opt in "${menu_options[@]}"
do
  if [ -n "$opt" ]; then
    # Extract metadata for the chosen name
    SELECTED_MODEL=$(python3 -c "import json; m = [m for m in json.load(open('$MODELS_JSON'))['models'] if m['name'] == '$opt'][0]; print(m['id'])")
    IS_DRY_RUN=$(python3 -c "import json; m = [m for m in json.load(open('$MODELS_JSON'))['models'] if m['name'] == '$opt'][0]; print(str(m['is_dry_run']).lower())")
    break
  else
    echo "❌ Invalid option. Please try again."
  fi
done

echo ""
if [ "$IS_DRY_RUN" = "true" ]; then
  echo "🔬 This is a dry run. No external requests are sent."
else
  echo "✅ Selected Model: $SELECTED_MODEL"
fi
echo "----------------------------------------------------------------"

# This safety check is essential if the selection is bypassed or fails
if [ -z "$SELECTED_MODEL" ]; then
  echo "❌ Error: No model was selected. Exiting."
  exit 1
fi

# --- METADATA VALIDATION ---
# Ensure .po files have the "Language: <TARGET_LANG>" header required by gpt-po-translator
echo "🔍 Validating .po metadata in $INPUT_HOST_DIR..."
for po_file in "$INPUT_HOST_DIR"/*.po; do
  [ -e "$po_file" ] || continue
  
  if ! grep -qi "Language: ${TARGET_LANG}" "$po_file"; then
    echo "📝 Adding missing language metadata to $(basename "$po_file")..."
    # Prepend the required string to the top of the file using a temporary file
    { printf "%s\n" "$REQUIRED_LANG_STR"; cat "$po_file"; } > "${po_file}.tmp" && mv "${po_file}.tmp" "$po_file"
  fi
done

# Check if there are any .po files in the output directory
if ls "${OUTPUT_HOST_DIR}"/*.po 1> /dev/null 2>&1; then
  echo "⚠️  WARNING: The output directory '${OUTPUT_HOST_DIR}' contains existing translation files."
  read -p "   Are you sure you want to DELETE them and start fresh? (y/N): " confirm
  if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "❌ Operation cancelled by user."
    exit 1
  fi
fi

# --- FILE PREPARATION ---
echo "🧹 Preparing output directory..."
# Ensure directory exists and is clean
docker compose exec toolbox sh -c 'mkdir -p /app/po/output && rm -f /app/po/output/*.po'

echo "📂 Copying fresh files..."
# Copy with archive mode (-a) to preserve attributes
docker compose exec toolbox sh -c 'cp -a /app/po/input/. /app/po/output/'

# CRITICAL: Fix permissions so python can overwrite files
docker compose exec toolbox sh -c 'chmod -R 777 /app/po/output'

echo "🚀 Starting Translation Runner..."

# Note: We use 'python3 -u' to unbuffer stdout so logs appear immediately
# Both input and output point to /app/po/output because we translate the copies
docker compose exec \
  toolbox python3 -u /app/src/translate_runner.py \
  --model "$SELECTED_MODEL" \
  --input "/app/po/output" \
  --output "/app/po/output"

# --- POST-PROCESSING ---
echo "✨ Running Post-Process (Drupal Standards)..."
docker compose exec toolbox python3 /app/src/post_process.py /app/po/output

echo "✅ Done!"
