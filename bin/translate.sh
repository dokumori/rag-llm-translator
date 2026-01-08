#!/bin/bash
# bin/translate.sh

# 1. Load environment variables (ignoring UID/GID to prevent shell errors)
if [ -f .env ]; then
  export $(grep -v '^#' .env | grep -vE '^(UID|GID)' | xargs)
elif [ -f ../.env ]; then
  export $(grep -v '^#' ../.env | grep -vE '^(UID|GID)' | xargs)
fi

set -e

# --- Model Selection Menu ---
echo "----------------------------------------------------------------"
echo "Please select the Amazee.ai (OpenAI-compatible) model to use:"
echo "----------------------------------------------------------------"

# Define the menu options properly
# Drupal Standard: 2-space indent
menu_options=(
  "DeepSeek R1 (deepseek-r1-v1)"
  "Claude 3.5 Sonnet (claude-3-5-sonnet)"
  "Claude Opus 4 (claude-opus-4-20250514-v1)"
  "Claude Sonnet 4 (claude-sonnet-4-20250514-v1)"
  "Mistral Large (mistral-large-2402-v1)"
  "Dry Run (No API calls)"
)

PS3="Enter the number of your choice: "

# Use 'select' with the correct variable name 'menu_options'
select opt in "${menu_options[@]}"
do
  case "$opt" in
    "DeepSeek R1 (deepseek-r1-v1)")
      SELECTED_MODEL="deepseek-r1-v1"
      break
      ;;
    "Claude 3.5 Sonnet (claude-3-5-sonnet)")
      SELECTED_MODEL="claude-3-5-sonnet"
      break
      ;;
    "Claude Opus 4 (claude-opus-4-20250514-v1)")
      SELECTED_MODEL="claude-opus-4-20250514-v1"
      break
      ;;
    "Claude Sonnet 4 (claude-sonnet-4-20250514-v1)")
      SELECTED_MODEL="claude-sonnet-4-20250514-v1"
      break
      ;;
    "Mistral Large (mistral-large-2402-v1)")
      SELECTED_MODEL="mistral-large-2402-v1"
      break
      ;;
    "Dry Run (No API calls)")
      # Preserving specific dry-run ID as requested
      SELECTED_MODEL="claude-opus-4-5-20251101"
      break
      ;;
    *)
      echo "❌ Invalid option. Please try again."
      ;;
  esac
done

# --- CRITICAL SAFETY CHECK ---
if [ -z "$SELECTED_MODEL" ]; then
  echo "❌ Error: No model was selected. Exiting."
  exit 1
fi

echo ""
echo "✅ Selected Model: $SELECTED_MODEL"
echo "----------------------------------------------------------------"

echo "🧹 Cleaning previous run..."
docker compose exec toolbox sh -c 'rm -rf /app/po/output/*'

echo "📂 Copying fresh files..."
# Explicitly copy files so they exist even if the script fails later
docker compose exec toolbox sh -c 'cp -r /app/po/input/. /app/po/output/'

# Ensure the copied files are writable (fix permission issues)
docker compose exec toolbox sh -c 'chmod -R 777 /app/po/output'
echo "🚀 Starting Translation Runner..."

# CORRECTED CONFIGURATION FOR PROXY USAGE:
# 1. OPENAI_BASE_URL points to the internal Docker service 'rag-proxy'
# 2. OPENAI_API_KEY can be a dummy value here, because the REAL key 
#    is stored in the proxy container (app.py)

docker compose exec \
  -e OPENAI_API_KEY="dummy-key-client" \
  -e OPENAI_BASE_URL="http://rag-proxy:5000/v1" \
  toolbox python3 /app/src/translate_runner.py \
  "$SELECTED_MODEL" \
  "/app/po/input" \
  "/app/po/output"

echo "✨ Post-processing variables..."
docker compose exec toolbox python3 /app/src/post_process.py /app/po/output

echo "✅ Done!"

###
#The default is 50. Reduced for improved accuracy (more costs)

# alternative models
# claude-3-opus-20240229  >> Use this for a dry-run. No actual API calls are made
# claude-3-haiku-20240307
# claude-haiku-4-5-20251001
# claude-sonnet-4-5-20250929
# claude-opus-4-5-20251101


#   -vv > debug_run.log 2>&1

# echo "✅ Done! Check debug_run.log for the full request payloads."
