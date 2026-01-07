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
echo "Please select the Anthropic model to use:"
echo "Pricing info: https://platform.claude.com/docs/en/about-claude/pricing"
echo "----------------------------------------------------------------"

# RENAMED from 'options' to 'menu_options' to avoid Zsh reserved variable conflict
menu_options=(
  "Dry Run (No API calls are made)"
  "Haiku 3 (claude-3-haiku-20240307)"
  "Haiku 4.5 (claude-haiku-4-5-20251001)"
  "Sonnet 4.5 (claude-sonnet-4-5-20250929)"
  "Opus 4.5 (claude-opus-4-5-20251101)"
)

PS3="Enter the number of your choice: "

# Use 'select' with the safe variable name
select opt in "${menu_options[@]}"
do
  case "$opt" in
    "Dry Run (No API calls are made)")
      SELECTED_MODEL="claude-opus-4-5-20251101"
      break
      ;;
    "Haiku 3 (claude-3-haiku-20240307)")
      SELECTED_MODEL="claude-3-haiku-20240307"
      break
      ;;
    "Haiku 4.5 (claude-haiku-4-5-20251001)")
      SELECTED_MODEL="claude-haiku-4-5-20251001"
      break
      ;;
    "Sonnet 4.5 (claude-sonnet-4-5-20250929)")
      SELECTED_MODEL="claude-sonnet-4-5-20250929"
      break
      ;;
    "Opus 4.5 (claude-opus-4-5-20251101)")
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
# (Files are read from input volume by the python script)

echo "🚀 Starting Translation Runner..."

# Call the Python Runner
docker compose exec \
  -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  -e ANTHROPIC_BASE_URL="http://rag-proxy:5000" \
  -e ANTHROPIC_API_URL="http://rag-proxy:5000" \
  -e ANTHROPIC_ENDPOINT_URL="http://rag-proxy:5000" \
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
