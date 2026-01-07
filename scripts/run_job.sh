#!/bin/bash
# run_job.sh

# Stop execution on errors
set -e

# --- Model Selection Menu ---
echo "----------------------------------------------------------------"
echo "Please select the Anthropic model to use:"
echo "Pricing info: https://platform.claude.com/docs/en/about-claude/pricing"
echo "----------------------------------------------------------------"

menu_options=(
  "Dry Run (No API calls are made)"
  "Haiku 3 (claude-3-haiku-20240307)"
  "Haiku 4.5 (claude-haiku-4-5-20251001)"
  "Sonnet 4.5 (claude-sonnet-4-5-20250929)"
  "Opus 4.5 (claude-opus-4-5-20251101)"
)

PS3="Enter the number of your choice: "

select opt in "${menu_options[@]}"
do
  case $opt in
    "Dry Run (No API calls are made)")
      # STRATEGY: Use the Opus model ID as the Dry Run signal.
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
    *) 
      echo "Invalid option $REPLY"
      ;;
  esac
done

echo ""
echo "✅ Selected Model: $SELECTED_MODEL"
echo "----------------------------------------------------------------"

echo "🧹 Cleaning previous run..."
docker exec drupal-translator mkdir -p /app/po/translated
docker exec drupal-translator sh -c 'rm -rf /app/po/translated/*'

echo "📂 Copying fresh files..."
docker exec drupal-translator cp -r /app/po/untranslated/. /app/po/translated/

echo "🚀 Starting Translation..."

# FIX: Pass EVERY known environment variable for Anthropic Base URLs.
# We also include '/v1' in the path, as some older clients require the full suffix.
docker exec \
  -e ANTHROPIC_BASE_URL="http://rag-proxy:5000" \
  -e ANTHROPIC_API_URL="http://rag-proxy:5000" \
  -e ANTHROPIC_ENDPOINT_URL="http://rag-proxy:5000" \
  drupal-translator gpt-po-translator \
  --provider anthropic \
  --model "$SELECTED_MODEL" \
  --folder /app/po/translated \
  --lang ja \
  --bulk \
  --bulksize 15

echo "✨ Post-processing variables..."
docker cp scripts/post_process.py drupal-translator:/app/post_process.py
docker exec drupal-translator python3 /app/post_process.py /app/po/translated

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
