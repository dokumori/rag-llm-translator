#!/bin/bash
# run_job.sh

# Stop execution on errors
set -e

echo "🧹 Cleaning previous run..."
# Ensure directory exists before emptying to prevent errors
docker exec drupal-translator mkdir -p /app/po/translated
docker exec drupal-translator sh -c 'rm -rf /app/po/translated/*'

echo "📂 Copying fresh files..."
docker exec drupal-translator cp -r /app/po/untranslated/. /app/po/translated/

echo "🚀 Starting Translation..."
docker exec drupal-translator gpt-po-translator \
  --provider anthropic \
  --model claude-haiku-4-5-20251001 \
  --folder /app/po/translated \
  --lang ja \
  --bulk \
  --bulksize 15

echo "✨ Post-processing variables..."
docker cp scripts/post_process.py drupal-translator:/app/post_process.py

# CHANGE: Point to the FOLDER, not the file.
docker exec drupal-translator python3 /app/post_process.py /app/po/translated

echo "✅ Done!"

###
#The default is 50. Reduced for improved accuracy (more costs)

# alternative models
#--model claude-3-haiku-20240307 \
#--model claude-haiku-4-5-20251001 \

#   -vv > debug_run.log 2>&1

# echo "✅ Done! Check debug_run.log for the full request payloads."
