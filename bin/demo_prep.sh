#/bin/bash

SOURCE_DIR="data/tm_source"
PO_FILE="${SOURCE_DIR}/drupal-11.0.6.ja.po"
PO_URL="https://ftp.drupal.org/files/translations/all/drupal/drupal-11.0.6.ja.po"

GLOSSARY_FILE="${SOURCE_DIR}/glossary.csv"
GLOSSARY_URL="https://www.drupal.org/files/issues/2026-01-22/glossary.csv"

TRANS_INPUT_DIR="data/translations/input"
EN_JA_PO_FILE="${TRANS_INPUT_DIR}/en-ja.po"
EN_JA_PO_URL="https://www.drupal.org/files/issues/2026-01-22/en-ja.po"

# Download the PO file w/translated strings if it's not already there
if [ ! -f "$PO_FILE" ]; then
  echo "📥 Downloading Drupal core translations (drupal-11.0.6.ja.po) for the demo..."
  curl -L -o "$PO_FILE" "$PO_URL"
else
  echo "✅ The file '$PO_FILE' already exists."
fi

# Download the glossary file if it's not already there
if [ ! -f "$GLOSSARY_FILE" ]; then
  echo "📥 Downloading demo glossary..."
  curl -L -o "$GLOSSARY_FILE" "$GLOSSARY_URL"
else
  echo "✅ The file '$GLOSSARY_FILE' already exists."
fi

# Ensure translation input directory exists
mkdir -p "$TRANS_INPUT_DIR"

# Download the PO file with untranslated strings if it's not already there
if [ ! -f "$EN_JA_PO_FILE" ]; then
  echo "📥 Downloading additional translations (en-ja.po) to $TRANS_INPUT_DIR..."
  curl -L -o "$EN_JA_PO_FILE" "$EN_JA_PO_URL"
else
  echo "✅ The file '$EN_JA_PO_FILE' already exists."
fi
