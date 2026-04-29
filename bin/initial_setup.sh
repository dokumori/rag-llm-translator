#!/bin/bash

# Get the project root directory
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo ""
echo "===================================================================="
echo " ⚙️ LLM INFORMATION"
echo "===================================================================="
# Prompt for credentials
read -p "Enter LLM API Token: " LLM_API_TOKEN
read -p "Enter LLM base URL: " LLM_BASE_URL


echo ""
echo "===================================================================="
echo " ⚙️ BULK SIZE"
echo "===================================================================="

# Prompt for Bulk Size
echo "Bulk Size: The number of strings sent to LLM at once along with RAG context. Smaller values improve context/quality but increase cost (due to higher total token usage)."
read -p "Enter BULK_SIZE (default: 15): " BULK_SIZE
BULK_SIZE=${BULK_SIZE:-15}

# RAG Thresholds: Fine-tune matching sensitivity.
# (Refer to docs/3_RAG_performance_analysis.md for details)
GLOSSARY_THRESHOLD=0.36
TM_THRESHOLD=0.27

# Empirical synonym guardrail
# See docs/3_RAG_performance_analysis.md before changing this value.
RAG_STRICT_DISTANCE_THRESHOLD=0.15



# 1. Detect actual UID/GID to ensure the container matches the host user
DETECTED_UID=$(id -u)
DETECTED_GID=$(id -g)

# 3. Create .env file with final values (No sed required)
echo "📝 Generating .env file..."
cat > "${PROJECT_ROOT}/.env" << EOF
# .env file - Generated on $(date '+%Y-%m-%d %H:%M')
LLM_API_TOKEN=${LLM_API_TOKEN}
LLM_BASE_URL=${LLM_BASE_URL}
BULK_SIZE=${BULK_SIZE}
# --- Post-Processing (Optional) ----------------------------------------
# To configure post-processing plugins, run:
#   bash bin/setup_post_processing.sh
#
# Or uncomment and edit manually. Plugins are per-language:
# POST_PROCESS_PLUGINS_JA=spacing_around_drupal_variables,jp_en_spacing
# POST_PROCESS_PLUGINS_ES=spacing_around_drupal_variables
# See docs/2_post_processing.md for details.
# ------------------------------------------------------------------------
POST_PROCESSING_ENABLED=false
GLOSSARY_THRESHOLD=${GLOSSARY_THRESHOLD}
TM_THRESHOLD=${TM_THRESHOLD}
RAG_STRICT_DISTANCE_THRESHOLD=${RAG_STRICT_DISTANCE_THRESHOLD}
CHROMA_PORT=8000

# User IDs for Docker Compose
UID=${DETECTED_UID}
GID=${DETECTED_GID}
EOF

# 4. Fix ownership of the data directory (Executed on Host)
echo "🔧 Setting folder permissions. You may be asked for the root password."
# Use numeric GID (${DETECTED_GID}) to avoid "illegal group name" errors
# entirely on Mac/Linux.
sudo chown -R ${DETECTED_UID}:${DETECTED_GID} "${PROJECT_ROOT}/data"
chmod -R 775 "${PROJECT_ROOT}/data"

echo "✅ Setup complete. Project root: ${PROJECT_ROOT}"
echo "To enable post-processing, run 'bash bin/setup_post_processing.sh'."
echo "If you want to run a demo, run 'bash bin/demo_prep.sh'."
echo "Refer to readme.MD for how to run the translation process."
echo "You can now run 'docker compose up -d'"
