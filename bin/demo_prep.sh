#/bin/bash

SOURCE_DIR="data/tm_source"
PO_FILE="${SOURCE_DIR}/drupal-11.0.6.ja.po"
PO_URL="https://ftp.drupal.org/files/translations/all/drupal/drupal-11.0.6.ja.po"

# Download the file if it's not already there
if [ ! -f "$PO_FILE" ]; then
  echo "📥 Downloading Drupal core translations for the demo..."
  curl -L -o "$PO_FILE" "$PO_URL"
else
  echo "✅ The file `$PO_FILE` already exists."
fi
