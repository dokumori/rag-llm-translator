#!/bin/bash
# run_job.sh

# Stop execution on errors
set -e

# --- Model Selection Menu ---
echo "----------------------------------------------------------------"
echo "Please select the Anthropic model to use:"
echo "Pricing info: https://platform.claude.com/docs/en/about-claude/pricing"
echo "----------------------------------------------------------------"

# 1. What the user sees
menu_options=(
  "Dry Run (No API calls are made)"
  "Haiku 3 (claude-3-haiku-20240307)"
  "Haiku 4.5 (claude-haiku-4-5-20251001)"
  "Sonnet 4.5 (claude-sonnet-4-5-20250929)"
  "Opus 4.5 (claude-opus-4-5-20251101)"
)

# 2. The actual IDs (Order must match the list above!)
model_ids=(
  "claude-3-opus-20240229" # Your dry run placeholder
  "claude-3-haiku-20240307"
  "claude-haiku-4-5-20251001"
  "claude-sonnet-4-5-20250929"
  "claude-opus-4-5-20251101"
)

PS3="Enter the number of your choice: "

select opt in "${menu_options[@]}"
do
  # Check if the input is a valid number within range
  if [[ -n "$opt" ]]; then
    # Map the user's number choice ($REPLY) to the model_ids array
    # We use $((REPLY-1)) because Bash arrays are 0-indexed
    SELECTED_MODEL="${model_ids[$((REPLY-1))]}"
    break
  else
    echo "Invalid option: $REPLY"
  fi
done

echo "You selected: $opt"
echo "Model ID: $SELECTED_MODEL"

echo ""
echo "✅ Selected Model: $SELECTED_MODEL"
echo "----------------------------------------------------------------"
echo ""

echo "🧹 Cleaning previous run..."
# Ensure directory exists before emptying to prevent errors
docker exec drupal-translator mkdir -p /app/po/translated
docker exec drupal-translator sh -c 'rm -rf /app/po/translated/*'

echo "📂 Copying fresh files..."
docker exec drupal-translator cp -r /app/po/untranslated/. /app/po/translated/

echo "🚀 Starting Translation..."
docker exec drupal-translator gpt-po-translator \
  --provider anthropic \
  --model "$SELECTED_MODEL" \
  --folder /app/po/translated \
  --lang ja \
  --bulk \
  --bulksize 15

echo "✨ Post-processing variables..."
docker cp scripts/post_process.py drupal-translator:/app/post_process.py

# Point to the FOLDER, not the file.
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
