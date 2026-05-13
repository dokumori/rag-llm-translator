#!/bin/bash
# bin/initial_setup.sh
#
# Interactive setup wizard for the RAG LLM Translation project.
# Guides the user through:
#   1. LLM connection mode  (Direct | Gateway | Local/Ollama)
#   2. API key collection   (per-provider, masked input)
#   3. LiteLLM config       (auto-generated for Gateway mode)
#   4. Gateway auto-start   (COMPOSE_PROFILES=gateway)
#   5. Bulk size & permissions (unchanged from previous version)
#   6. Embedding model download

set -euo pipefail

# ── Paths ─────────────────────────────────────────────────────────────────────
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="${PROJECT_ROOT}/.env-backups"
ENV_FILE="${PROJECT_ROOT}/.env"
LITELLM_CONFIG="${PROJECT_ROOT}/config/litellm/config.yaml"
LITELLM_EXAMPLE="${PROJECT_ROOT}/config/litellm/config.example.yaml"
CUSTOM_MODELS="${PROJECT_ROOT}/config/models/custom/models.json"
MODELS_EXAMPLE="${PROJECT_ROOT}/config/models/custom/models.example.json"

# ── Colours ───────────────────────────────────────────────────────────────────
BOLD="\033[1m"
RESET="\033[0m"
DIM="\033[2m"

section() { echo ""; echo -e "${BOLD}════════════════════════════════════════════════════${RESET}"; echo -e "${BOLD} $1${RESET}"; echo -e "${BOLD}════════════════════════════════════════════════════${RESET}"; }
info()    { echo "   $1"; }

# ── .env Backup ───────────────────────────────────────────────────────────────
# ── .env Backup ───────────────────────────────────────────────────────────────
# Always back up an existing .env before overwriting it.
if [ -f "$ENV_FILE" ]; then
    echo ""
    echo "⚠️  An existing .env was found. This script will overwrite it."
    read -p "   Back up .env before proceeding? [Y/n]: " BACKUP_CHOICE
    BACKUP_CHOICE="${BACKUP_CHOICE:-Y}"
    if [[ "$BACKUP_CHOICE" =~ ^[Yy]$ ]]; then
        mkdir -p "$BACKUP_DIR"
        BACKUP_FILE="${BACKUP_DIR}/.env-$(date '+%Y%m%d-%H%M%S')"
        cp "$ENV_FILE" "$BACKUP_FILE"
        echo "   📦 Backed up to: .env-backups/$(basename "$BACKUP_FILE")"
    else
        echo "   ⏭️  Skipping backup."
    fi
fi

# ── LLM Mode selection ────────────────────────────────────────────────────────
SETUP_MODE=""
LLM_BASE_URL=""
LLM_API_TOKEN=""
ANTHROPIC_API_KEY=""
OPENAI_API_KEY=""
GEMINI_API_KEY=""
MISTRAL_API_KEY=""
COMPOSE_PROFILES=""
SELECTED_PROVIDERS=()

section "⚙️  LLM CONNECTION MODE"
    echo "   How will you connect to your LLM?"
    echo ""
    echo "   1) Direct  — I have an OpenAI-compatible endpoint"
    echo "                (amazee.ai, vLLM, Mistral La Plateforme, etc.)"
    echo "   2) Gateway — Use the built-in LiteLLM proxy"
    echo "                (Anthropic, Google, OpenAI, Mistral, …)"
    echo "   3) Local   — I'm running Ollama on this machine"
    echo "                (URL is auto-configured)"
    echo ""
    read -p "   Your choice [1/2/3]: " MODE_CHOICE

    case "$MODE_CHOICE" in
        1)
            SETUP_MODE="direct"
            echo ""
            read -p "   Enter LLM base URL: " LLM_BASE_URL
            read -p "   Enter LLM API Token: " LLM_API_TOKEN
            ;;

        3)
            SETUP_MODE="local"
            LLM_BASE_URL="http://host.docker.internal:11434/v1"
            LLM_API_TOKEN=""
            echo ""
            echo "   ✅ LLM_BASE_URL set to: ${LLM_BASE_URL}"
            echo "   ℹ️  Make sure Ollama is running on your host before starting Docker Compose."
            ;;

        2)
            SETUP_MODE="gateway"

            # ── Provider selection ─────────────────────────────────────────
            section "⚙️  PROVIDER SELECTION"
            echo "   Which providers do you want to enable?"
            echo "   Enter the numbers separated by spaces (e.g. 1 2):"
            echo ""
            echo "   1) Anthropic (Claude)"
            echo "   2) Google    (Gemini)"
            echo "   3) OpenAI    (GPT-4o, o-series)"
            echo "   4) Mistral"
            echo ""
            read -p "   Your choices: " PROVIDER_CHOICES

            for c in $PROVIDER_CHOICES; do
                case "$c" in
                    1) SELECTED_PROVIDERS+=("anthropic") ;;
                    2) SELECTED_PROVIDERS+=("google")    ;;
                    3) SELECTED_PROVIDERS+=("openai")    ;;
                    4) SELECTED_PROVIDERS+=("mistral")   ;;
                    *) echo "   ⚠️  Ignoring unknown provider choice: $c" ;;
                esac
            done

            if [ ${#SELECTED_PROVIDERS[@]} -eq 0 ]; then
                echo "❌ No providers selected. Exiting."
                exit 1
            fi

            # ── API key prompts ────────────────────────────────────────────
            section "⚙️  API KEYS"
            echo "   Enter your API key for each selected provider."
            echo "   (Input is hidden)"
            echo ""

            for p in "${SELECTED_PROVIDERS[@]}"; do
                case "$p" in
                    anthropic)
                        while true; do
                            read -s -p "   ANTHROPIC_API_KEY: " ANTHROPIC_API_KEY
                            echo ""
                            [ -n "$ANTHROPIC_API_KEY" ] && break
                            echo "   ⚠️  Key cannot be empty. Please try again."
                        done
                        ;;
                    google)
                        while true; do
                            read -s -p "   GEMINI_API_KEY: " GEMINI_API_KEY
                            echo ""
                            [ -n "$GEMINI_API_KEY" ] && break
                            echo "   ⚠️  Key cannot be empty. Please try again."
                        done
                        ;;
                    openai)
                        while true; do
                            read -s -p "   OPENAI_API_KEY: " OPENAI_API_KEY
                            echo ""
                            [ -n "$OPENAI_API_KEY" ] && break
                            echo "   ⚠️  Key cannot be empty. Please try again."
                        done
                        ;;
                    mistral)
                        while true; do
                            read -s -p "   MISTRAL_API_KEY: " MISTRAL_API_KEY
                            echo ""
                            [ -n "$MISTRAL_API_KEY" ] && break
                            echo "   ⚠️  Key cannot be empty. Please try again."
                        done
                        ;;
                esac
            done

            # Gateway URL used by the app to reach the proxy
            LLM_BASE_URL="http://litellm:4000/v1"
            LLM_API_TOKEN=""

            # ── Auto-start prompt ──────────────────────────────────────────
            section "⚙️  GATEWAY AUTO-START"
            echo "   Should the LiteLLM gateway start automatically with 'docker compose up'?"
            echo ""
            echo "   1) Yes — always start the gateway  (COMPOSE_PROFILES=gateway)"
            echo "   2) No  — start it manually when needed"
            echo ""
            read -p "   Your choice [1/2]: " AUTOSTART_CHOICE
            if [ "${AUTOSTART_CHOICE:-1}" = "1" ]; then
                COMPOSE_PROFILES="gateway"
            fi

            # ── Generate LiteLLM config.yaml ───────────────────────────────
            section "📝 GENERATING LITELLM CONFIG"

            if [ ! -f "$LITELLM_EXAMPLE" ]; then
                echo "❌ Example config not found: config/litellm/config.example.yaml"
                echo "   Please ensure the repository is intact and try again."
                exit 1
            fi

            # Overwrite prompt if config.yaml already exists
            if [ -f "$LITELLM_CONFIG" ]; then
                read -p "   config/litellm/config.yaml already exists. Overwrite? [y/N]: " OW
                OW="${OW:-N}"
                if [[ ! "$OW" =~ ^[Yy]$ ]]; then
                    echo "   ⏭️  Keeping existing config.yaml."
                    LITELLM_CONFIG=""   # signal: skip generation
                fi
            fi

            if [ -n "$LITELLM_CONFIG" ]; then
                {
                    echo "# LiteLLM Gateway Configuration"
                    echo "# Auto-generated by initial_setup.sh on $(date '+%Y-%m-%d %H:%M')"
                    echo "# To add more models, edit this file or re-run bin/initial_setup.sh."
                    echo ""
                    echo "model_list:"
                } > "$LITELLM_CONFIG"

                for p in "${SELECTED_PROVIDERS[@]}"; do
                    case "$p" in
                        anthropic)
                            cat >> "$LITELLM_CONFIG" << 'ANTHROPIC_BLOCK'

  # ---------------------------------------------------------------------------
  # Anthropic — Claude models
  # ---------------------------------------------------------------------------
  - model_name: claude-haiku-4-5
    litellm_params:
      model: anthropic/claude-haiku-4-5-20251001
      api_key: os.environ/ANTHROPIC_API_KEY

  - model_name: claude-sonnet-4-6
    litellm_params:
      model: anthropic/claude-sonnet-4-6
      api_key: os.environ/ANTHROPIC_API_KEY

  - model_name: claude-opus-4-7
    litellm_params:
      model: anthropic/claude-opus-4-7
      api_key: os.environ/ANTHROPIC_API_KEY
ANTHROPIC_BLOCK
                            ;;
                        google)
                            cat >> "$LITELLM_CONFIG" << 'GOOGLE_BLOCK'

  # ---------------------------------------------------------------------------
  # Google — Gemini models
  # ---------------------------------------------------------------------------
  - model_name: gemini-2.5-pro
    litellm_params:
      model: gemini/gemini-2.5-pro
      api_key: os.environ/GEMINI_API_KEY

  - model_name: gemini-2.5-flash
    litellm_params:
      model: gemini/gemini-2.5-flash
      api_key: os.environ/GEMINI_API_KEY

  - model_name: gemini-2.5-flash-lite
    litellm_params:
      model: gemini/gemini-2.5-flash-lite
      api_key: os.environ/GEMINI_API_KEY
GOOGLE_BLOCK
                            ;;
                        openai)
                            cat >> "$LITELLM_CONFIG" << 'OPENAI_BLOCK'

  # ---------------------------------------------------------------------------
  # OpenAI — GPT-4o and o-series reasoning models
  # Note: LiteLLM automatically handles temperature / max_completion_tokens
  # differences for o-series models.
  # ---------------------------------------------------------------------------
  - model_name: gpt-4o
    litellm_params:
      model: openai/gpt-4o
      api_key: os.environ/OPENAI_API_KEY

  - model_name: o4-mini
    litellm_params:
      model: openai/o4-mini
      api_key: os.environ/OPENAI_API_KEY

  - model_name: o3-mini
    litellm_params:
      model: openai/o3-mini
      api_key: os.environ/OPENAI_API_KEY
OPENAI_BLOCK
                            ;;
                        mistral)
                            cat >> "$LITELLM_CONFIG" << 'MISTRAL_BLOCK'

  # ---------------------------------------------------------------------------
  # Mistral
  # ---------------------------------------------------------------------------
  - model_name: mistral-large-3
    litellm_params:
      model: mistral/mistral-large-latest
      api_key: os.environ/MISTRAL_API_KEY
MISTRAL_BLOCK
                            ;;
                    esac
                done

                echo "   ✅ Written: config/litellm/config.yaml"
            fi

            # ── Generate custom models.json ────────────────────────────────
            GENERATE_CUSTOM_MODELS=true
            if [ ! -f "$MODELS_EXAMPLE" ]; then
                echo "   ⚠️  models.example.json not found — skipping custom models.json generation."
                GENERATE_CUSTOM_MODELS=false
            elif [ -f "$CUSTOM_MODELS" ]; then
                read -p "   config/models/custom/models.json already exists. Overwrite? [y/N]: " OW_MODELS
                OW_MODELS="${OW_MODELS:-N}"
                if [[ ! "$OW_MODELS" =~ ^[Yy]$ ]]; then
                    echo "   ⏭️  Keeping existing models.json."
                    GENERATE_CUSTOM_MODELS=false
                fi
            fi
            if [ "$GENERATE_CUSTOM_MODELS" = true ]; then
                PROVIDERS_ARG="${SELECTED_PROVIDERS[*]}"
                python3 - "$PROVIDERS_ARG" "$MODELS_EXAMPLE" "$CUSTOM_MODELS" << 'PYEOF'
import json, sys

providers_str, example_path, output_path = sys.argv[1], sys.argv[2], sys.argv[3]
providers = providers_str.split()

prefixes = {
    "anthropic": ["claude-"],
    "google":    ["gemini-"],
    "openai":    ["gpt-", "o3-", "o4-"],
    "mistral":   ["mistral-"],
}

with open(example_path) as f:
    example = json.load(f)

selected = []
for m in example.get("models", []):
    mid = m.get("id", "")
    for p in providers:
        if any(mid.startswith(pfx) for pfx in prefixes.get(p, [])):
            selected.append(m)
            break

# Always include the dry-run entry from the example if present
dry_run = next((m for m in example.get("models", []) if m.get("is_dry_run")), None)
if dry_run and dry_run not in selected:
    selected.append(dry_run)

with open(output_path, "w") as f:
    json.dump({"models": selected}, f, indent=2)
    f.write("\n")
PYEOF
                echo "   ✅ Written: config/models/custom/models.json"
            fi

            ;;

        *)
            echo "❌ Invalid choice. Exiting."
            exit 1
            ;;
    esac

    # ── Bulk Size ──────────────────────────────────────────────────────────────
    section "⚙️  BULK SIZE"
    echo "   The number of strings sent to the LLM at once with RAG context."
    echo "   Smaller values improve quality but increase cost."
    echo ""
    read -p "   Enter BULK_SIZE (default: 15): " BULK_SIZE
    BULK_SIZE=${BULK_SIZE:-15}



# ── Shared values (always needed for .env write and permissions) ───────────────
# RAG Thresholds: calibrated for the default embedding model.
# (Refer to docs/3_RAG_performance_analysis.md for details)
GLOSSARY_THRESHOLD=0.36
TM_THRESHOLD=0.27
RAG_STRICT_DISTANCE_THRESHOLD=0.15

DETECTED_UID=$(id -u)
DETECTED_GID=$(id -g)

# Read canonical embedding model default
if [ -f "${PROJECT_ROOT}/.env.defaults" ]; then
    EMBEDDING_MODEL_NAME=$(grep -m1 '^EMBEDDING_MODEL_NAME=' "${PROJECT_ROOT}/.env.defaults" | cut -d= -f2-)
fi
EMBEDDING_MODEL_NAME=${EMBEDDING_MODEL_NAME:-BAAI/bge-large-en-v1.5}



# ── Confirmation summary ───────────────────────────────────────────────────────
section "📋 SETUP SUMMARY"

    case "$SETUP_MODE" in
        direct)
            info "Mode:         Direct (OpenAI-compatible endpoint)"
            info "LLM URL:      ${LLM_BASE_URL}"
            info "API Token:    (set)"
            ;;
        local)
            info "Mode:         Local (Ollama)"
            info "LLM URL:      ${LLM_BASE_URL}"
            info "API Token:    (none required)"
            ;;
        gateway)
            info "Mode:         LiteLLM Gateway"
            PROVIDERS_DISPLAY=$(IFS=, ; echo "${SELECTED_PROVIDERS[*]^}" | sed 's/,/, /g')
            info "Providers:    ${PROVIDERS_DISPLAY}"
            [ -n "$ANTHROPIC_API_KEY" ] && info "              ANTHROPIC_API_KEY  ✅ set"
            [ -n "$GEMINI_API_KEY"    ] && info "              GEMINI_API_KEY     ✅ set"
            [ -n "$OPENAI_API_KEY"    ] && info "              OPENAI_API_KEY     ✅ set"
            [ -n "$MISTRAL_API_KEY"   ] && info "              MISTRAL_API_KEY    ✅ set"
            if [ -n "$COMPOSE_PROFILES" ]; then
                info "Auto-start:   Yes (COMPOSE_PROFILES=gateway)"
            else
                info "Auto-start:   No (start manually with --profile gateway)"
            fi
            ;;
    esac
    info "Bulk size:    ${BULK_SIZE}"

echo ""
read -p "   Proceed? [Y/n]: " CONFIRM
CONFIRM="${CONFIRM:-Y}"
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "   ❌ Aborted. No files were written."
    exit 0
fi

# ── Write .env ─────────────────────────────────────────────────────────────────
    echo ""
    echo "📝 Generating .env file..."

    # Build the provider-key block — only write keys that are set
    PROVIDER_KEYS_BLOCK=""
    if [ -n "$ANTHROPIC_API_KEY" ]; then
        PROVIDER_KEYS_BLOCK="${PROVIDER_KEYS_BLOCK}ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
"
    fi
    if [ -n "$GEMINI_API_KEY" ]; then
        PROVIDER_KEYS_BLOCK="${PROVIDER_KEYS_BLOCK}GEMINI_API_KEY=${GEMINI_API_KEY}
"
    fi
    if [ -n "$OPENAI_API_KEY" ]; then
        PROVIDER_KEYS_BLOCK="${PROVIDER_KEYS_BLOCK}OPENAI_API_KEY=${OPENAI_API_KEY}
"
    fi
    if [ -n "$MISTRAL_API_KEY" ]; then
        PROVIDER_KEYS_BLOCK="${PROVIDER_KEYS_BLOCK}MISTRAL_API_KEY=${MISTRAL_API_KEY}
"
    fi

    # Build COMPOSE_PROFILES line (only for gateway auto-start)
    COMPOSE_PROFILES_LINE=""
    if [ -n "$COMPOSE_PROFILES" ]; then
        COMPOSE_PROFILES_LINE="COMPOSE_PROFILES=${COMPOSE_PROFILES}"
    fi

    cat > "$ENV_FILE" << EOF
# .env file — Generated by initial_setup.sh on $(date '+%Y-%m-%d %H:%M')
# Setup mode: ${SETUP_MODE}

# --- LLM Connection -----------------------------------------------------------
LLM_BASE_URL=${LLM_BASE_URL}
LLM_API_TOKEN=${LLM_API_TOKEN}

# --- Provider API Keys (LiteLLM Gateway) --------------------------------------
# Only the keys for your selected providers are populated below.
${PROVIDER_KEYS_BLOCK}
# --- LiteLLM Gateway Auto-start -----------------------------------------------
# Set COMPOSE_PROFILES=gateway to start the gateway with every 'docker compose up'.
# Remove or comment out to start the gateway manually:
#   docker compose --profile gateway up -d
${COMPOSE_PROFILES_LINE}

# --- Bulk Size ----------------------------------------------------------------
BULK_SIZE=${BULK_SIZE}

# --- Post-Processing (Optional) -----------------------------------------------
# To configure post-processing plugins, run:
#   bash bin/setup_post_processing.sh
#
# Or uncomment and edit manually. Plugins are per-language:
# POST_PROCESS_PLUGINS_JA=spacing_around_drupal_variables,jp_en_spacing
# POST_PROCESS_PLUGINS_ES=spacing_around_drupal_variables
# See docs/2_post_processing.md for details.
# ------------------------------------------------------------------------------
POST_PROCESSING_ENABLED=false

# --- RAG Thresholds -----------------------------------------------------------
# Calibrated for the default embedding model (BAAI/bge-large-en-v1.5).
# If any threshold is 0.4, it has not been calibrated — see
# docs/3_RAG_performance_analysis.md before using in production.
GLOSSARY_THRESHOLD=${GLOSSARY_THRESHOLD}
TM_THRESHOLD=${TM_THRESHOLD}
RAG_STRICT_DISTANCE_THRESHOLD=${RAG_STRICT_DISTANCE_THRESHOLD}

# --- ChromaDB -----------------------------------------------------------------
CHROMA_PORT=8000

# --- Embedding Model ----------------------------------------------------------
EMBEDDING_MODEL_NAME=${EMBEDDING_MODEL_NAME}

# --- User IDs for Docker Compose ----------------------------------------------
UID=${DETECTED_UID}
GID=${DETECTED_GID}
EOF



# ── Permissions ────────────────────────────────────────────────────────────────
echo ""
echo "🔧 Setting folder permissions. You may be asked for your password."
sudo chown -R "${DETECTED_UID}:${DETECTED_GID}" "${PROJECT_ROOT}/data"
chmod -R 775 "${PROJECT_ROOT}/data"

echo ""
echo "✅ Setup complete. Project root: ${PROJECT_ROOT}"

# ── Embedding model download ───────────────────────────────────────────────────
echo ""
section "📦 EMBEDDING MODEL"
echo "   Downloading the default embedding model (${EMBEDDING_MODEL_NAME})."
echo "   This is a one-time download (~1.3GB)."
bash "${PROJECT_ROOT}/bin/download-model.sh"

# ── Next steps ─────────────────────────────────────────────────────────────────
echo ""
echo "📢 To enable post-processing, run 'bash bin/setup_post_processing.sh'."
echo ""
echo "📢 If you want to run a demo, run 'bash bin/demo_prep.sh'."
echo ""
echo "📢 Refer to README.md for how to run the translation process."
echo ""
echo "📢 The default embedding model is ${EMBEDDING_MODEL_NAME}."
echo "   To switch models, run 'bash bin/switch-embedding-model.sh'."
echo ""
if [ "$SETUP_MODE" = "gateway" ] && [ -z "$COMPOSE_PROFILES" ]; then
    echo "📢 Start the LiteLLM gateway manually when needed:"
    echo "     docker compose --profile gateway up -d"
    echo ""
fi
echo "📢 You can now run 'docker compose up -d'."
