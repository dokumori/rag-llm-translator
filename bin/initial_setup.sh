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
echo " ⚙️ TARGET LANGUAGE AND BULK SIZE"
echo "===================================================================="
# Prompt for Target Language (default to 'ja')
read -p "Enter TARGET_LANG (default: ja): " TARGET_LANG
TARGET_LANG=${TARGET_LANG:-ja}

# Prompt for Bulk Size
echo "Bulk Size: The number of strings sent to LLM at once along with RAG context. Smaller is better context/quality but more expensive (more total tokens used)."
read -p "Enter BULK_SIZE (default: 15): " BULK_SIZE
BULK_SIZE=${BULK_SIZE:-15}

# Prompt for RAG Thresholds
echo ""
echo "===================================================================="
echo " 🌡️ RAG THRESHOLDS CONFIGURATION"
echo "   (Refer to docs/3_RAG_performance_analysis.md for details)"
echo "===================================================================="
echo "RAG Thresholds: Fine-tune matching sensitivity."
read -p "Enter TM_THRESHOLD (default: 0.23): " TM_THRESHOLD
TM_THRESHOLD=${TM_THRESHOLD:-0.23}

read -p "Enter GLOSSARY_THRESHOLD (default: 0.25): " GLOSSARY_THRESHOLD
GLOSSARY_THRESHOLD=${GLOSSARY_THRESHOLD:-0.25}

read -p "Enter RAG_STRICT_DISTANCE_THRESHOLD (default: 0.08): " RAG_STRICT_DISTANCE_THRESHOLD
RAG_STRICT_DISTANCE_THRESHOLD=${RAG_STRICT_DISTANCE_THRESHOLD:-0.08}
echo "===================================================================="
echo ""

# Prompt for Post-Processing (Drupal/CJK Cleanup)
echo ""
echo "===================================================================="
echo " ⚙️  POST-PROCESSING PLUGINS"
echo "   (Refer to docs/2_post_processing.md for details)"
echo "===================================================================="
read -p "Enable Post-Processing? [y/N] (default: No): " ENABLE_POST_PROC
case "$ENABLE_POST_PROC" in
  [yY][eE][sS]|[yY]) POST_PROCESSING_ENABLED=true ;;
  *) POST_PROCESSING_ENABLED=false ;;
esac

# Initialize to empty string to prevent issues if disabled
POST_PROCESS_PLUGINS=""

if [ "$POST_PROCESSING_ENABLED" = "true" ]; then
    # Dynamic Plugin Discovery
    # Look in default and custom plugin directories
    PLUGIN_DIR_DEFAULT="./services/toolbox/src/plugins/default"
    PLUGIN_DIR_CUSTOM="./services/toolbox/src/plugins/custom"
    
    # helper to list python files without extension
    list_plugins() {
        find "$1" -maxdepth 1 -name "*.py" -not -name "__init__.py" -exec basename {} .py \; 2>/dev/null
    }

    PLUGINS_DEFAULT=$(list_plugins "$PLUGIN_DIR_DEFAULT" | tr '\n' ',')
    PLUGINS_CUSTOM=$(list_plugins "$PLUGIN_DIR_CUSTOM" | tr '\n' ',')
    
    # Combine and trim trailing commas
    ALL_PLUGINS="${PLUGINS_DEFAULT}${PLUGINS_CUSTOM}"
    ALL_PLUGINS=${ALL_PLUGINS%,} # Remove trailing comma if exists
    
    # Fallback default if nothing found (shouldn't happen with our default list)
    DEFAULT_SUGGESTION=${ALL_PLUGINS:-"spacing_around_drupal_variables,jp_en_spacing"}

    echo "🔌 Available Plugins:"
    echo "$DEFAULT_SUGGESTION" | tr ',' '\n' | while read -r plugin; do
        if [ -n "$plugin" ]; then
            echo "   - $plugin"
        fi
    done
    echo "   Enter a comma-separated list of plugins to run."
    echo "   (Note: Plugins will be executed in the order you list)."
    read -p "Plugins to run [default: $DEFAULT_SUGGESTION]: " CHECK_PLUGINS
    POST_PROCESS_PLUGINS=${CHECK_PLUGINS:-$DEFAULT_SUGGESTION}
fi

# 1. Detect actual UID/GID to ensure the container matches the host user
DETECTED_UID=$(id -u)
DETECTED_GID=$(id -g)

# 3. Create .env file with final values (No sed required)
echo "📝 Generating .env file..."
cat > "${PROJECT_ROOT}/.env" << EOF
# .env file - Generated on $(date '+%Y-%m-%d %H:%M')
LLM_API_TOKEN=${LLM_API_TOKEN}
LLM_BASE_URL=${LLM_BASE_URL}
TARGET_LANG=${TARGET_LANG}
BULK_SIZE=${BULK_SIZE}
POST_PROCESSING_ENABLED=${POST_PROCESSING_ENABLED}
POST_PROCESS_PLUGINS=${POST_PROCESS_PLUGINS}
TM_THRESHOLD=${TM_THRESHOLD}
GLOSSARY_THRESHOLD=${GLOSSARY_THRESHOLD}
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
echo "If you want to run a demo, run 'bash bin/demo_prep.sh'."
echo "Refer to readme.MD for how to run the translation process."
echo "You can now run 'docker compose up -d'"
