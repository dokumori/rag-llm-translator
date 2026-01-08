#!/bin/bash
# bin/translate.sh

# Load environment variables
if [ -f .env ]; then
  export $(grep -v '^#' .env | grep -vE '^(UID|GID)' | xargs)
fi

set -e

echo "----------------------------------------------------------------"
echo "Please select the Amazee.ai (OpenAI-compatible) model to use:"
echo "----------------------------------------------------------------"

menu_options=(
  "Dry Run (No API calls)"
  "DeepSeek R1 (deepseek-r1-v1)"
  "Claude 3.5 Sonnet (claude-3-5-sonnet)"
  "Claude Opus 4 (claude-opus-4-20250514-v1)"
  "Claude Sonnet 4 (claude-sonnet-4-20250514-v1)"
  "Mistral Large (mistral-large-2402-v1)"
)

PS3="Enter the number of your choice: "

select opt in "${menu_options[@]}"
do
  case "$opt" in
    "Dry Run (No API calls)") SELECTED_MODEL="claude-opus-4-5-20251101"; break ;;
    "DeepSeek R1 (deepseek-r1-v1)") SELECTED_MODEL="deepseek-r1-v1"; break ;;
    "Claude 3.5 Sonnet (claude-3-5-sonnet)") SELECTED_MODEL="claude-3-5-sonnet"; break ;;
    "Claude Opus 4 (claude-opus-4-20250514-v1)") SELECTED_MODEL="claude-opus-4-20250514-v1"; break ;;
    "Claude Sonnet 4 (claude-sonnet-4-20250514-v1)") SELECTED_MODEL="claude-sonnet-4-20250514-v1"; break ;;
    "Mistral Large (mistral-large-2402-v1)") SELECTED_MODEL="mistral-large-2402-v1"; break ;;
    *) echo "❌ Invalid option. Please try again.";;
  esac
done

if [ -z "$SELECTED_MODEL" ]; then
  echo "❌ Error: No model was selected. Exiting."
  exit 1
fi

echo ""
echo "✅ Selected Model: $SELECTED_MODEL"
echo "----------------------------------------------------------------"

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
  -e OPENAI_API_KEY="dummy" \
  -e OPENAI_BASE_URL="http://rag-proxy:5000/v1" \
  toolbox python3 -u /app/src/translate_runner.py \
  "$SELECTED_MODEL" \
  "/app/po/input" \
  "/app/po/output"

echo "✅ Done!"
