#!/bin/bash
# bin/translate.sh

# Load environment variables
if [ -f .env ]; then
  export $(grep -v '^#' .env | grep -vE '^(UID|GID)' | xargs)
fi

set -e

echo "----------------------------------------------------------------"
echo "Please select the LLM model to use:"
echo "----------------------------------------------------------------"

MODELS_JSON="config/models.json"

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

if [ -z "$SELECTED_MODEL" ]; then
  echo "❌ Error: No model was selected. Exiting."
  exit 1
fi

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
docker compose exec \
  toolbox python3 -u /app/src/translate_runner.py \
  "$SELECTED_MODEL" \
  "/app/po/input" \
  "/app/po/output"

# --- POST-PROCESSING ---
echo "✨ Running Post-Process (Drupal Standards)..."
docker compose exec toolbox python3 /app/src/post_process.py /app/po/output

echo "✅ Done!"
