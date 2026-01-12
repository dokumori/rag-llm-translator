#!/bin/bash

# Get the project root directory
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Prompt for credentials
read -p "Enter AMAZEE_API_TOKEN: " AMAZEE_API_TOKEN
read -p "Enter OPENAI_API_BASE: " OPENAI_API_BASE

# Prompt for Target Language (default to 'ja')
read -p "Enter TARGET_LANG (default: ja): " TARGET_LANG
TARGET_LANG=${TARGET_LANG:-ja}

# 1. Detect actual UID/GID to ensure the container matches the host user
DETECTED_UID=$(id -u)
DETECTED_GID=$(id -g)

# 2. Create required host directories (Executed on Host)
echo "📁 Creating data directories..."
mkdir -p "${PROJECT_ROOT}/data/cache"
mkdir -p "${PROJECT_ROOT}/data/rag-analysis"
mkdir -p "${PROJECT_ROOT}/data/glossary"
mkdir -p "${PROJECT_ROOT}/data/translations"
mkdir -p "${PROJECT_ROOT}/data/chroma_db"

# 3. Create .env file with final values (No sed required)
echo "📝 Generating .env file..."
cat > "${PROJECT_ROOT}/.env" << EOF
# .env file - Generated on $(date)
AMAZEE_API_TOKEN=${AMAZEE_API_TOKEN}
OPENAI_API_BASE=${OPENAI_API_BASE}
TARGET_LANG=${TARGET_LANG}
CHROMA_PORT=8000

# User IDs for Docker Compose
UID=${DETECTED_UID}
GID=${DETECTED_GID}
EOF

# 4. Fix ownership of the data directory (Executed on Host)
echo "🔧 Setting folder permissions..."
# Use numeric GID (${DETECTED_GID}) to avoid "illegal group name" errors
# entirely on Mac/Linux.
sudo chown -R ${DETECTED_UID}:${DETECTED_GID} "${PROJECT_ROOT}/data"
chmod -R 775 "${PROJECT_ROOT}/data"

echo "✅ Setup complete. Project root: ${PROJECT_ROOT}"
echo "🚀 You can now run 'docker compose up -d'"
