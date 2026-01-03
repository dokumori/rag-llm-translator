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
# Removed -it for better automation compatibility
# Updated model to current 2026 standard (Claude Haiku 4.5)
docker exec drupal-translator gpt-po-translator \
  --provider anthropic \
  --model claude-3-haiku-20240307 \
  --folder /app/po/translated \
  --lang ja \
  --bulk \
  -vv' > debug_run.log 2>&1

echo "✅ Done! Check debug_run.log for the full request payloads."
