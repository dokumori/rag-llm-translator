#!/bin/bash
# bin/setup.sh
#
# Interactive setup wizard for the RAG LLM Translation project.
# Guides the user through:
#   1. LLM connection mode  (Gateway | Local/Ollama)
#   2. API key collection   (per-provider, masked input)
#   3. LiteLLM config       (auto-generated for Gateway mode)
#   4. Bulk size & permissions
#   5. Embedding model download

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
CUSTOM_LLM_BASE_URLS=()
CUSTOM_LLM_API_KEYS=()
CUSTOM_MODEL_NAMES=()
CUSTOM_REMOTE_MODEL_IDS=()
CUSTOM_MODEL_DISPLAYS=()
DEDUP_URLS=()
DEDUP_KEYS=()
ENDPOINT_ENV_IDX=()
OLLAMA_BASE_URL=""
OLLAMA_MODELS=""

SELECTED_PROVIDERS=()

section "⚙️  LLM CONNECTION MODE"
    echo "   How will you connect to your LLM?"
    echo ""
    echo "   1) Gateway — Connect to cloud providers or local models via the built-in proxy"
    echo "                (Anthropic, Google, OpenAI, Mistral, amazee.ai, Ollama, vLLM, and more)"
    echo "                (mix providers freely — switch models without changing config)"
    echo ""
    echo "   2) Local   — Ollama only, no cloud providers"
    echo "                (URL is auto-configured; choose Gateway to mix Ollama with cloud)"
    echo ""
    read -p "   Your choice [1/2]: " MODE_CHOICE

    case "$MODE_CHOICE" in
        2)
            SETUP_MODE="local"
            LLM_BASE_URL="http://host.docker.internal:11434/v1"
            LLM_API_TOKEN=""
            echo ""
            echo "   ✅ LLM_BASE_URL set to: ${LLM_BASE_URL}"
            echo "   ℹ️  Make sure Ollama is running on your host before starting Docker Compose."
            ;;

        1)
            SETUP_MODE="gateway"

            # ── Provider selection ─────────────────────────────────────────
            section "⚙️  PROVIDER SELECTION"
            echo "   Which providers do you want to enable?"
            echo "   Enter the numbers separated by spaces (e.g. 1 2 5):"
            echo ""
            echo "   1) Anthropic (Claude)"
            echo "   2) Google    (Gemini)"
            echo "   3) OpenAI    (GPT-4o, o-series)"
            echo "   4) Mistral"
            echo "   5) Custom    (amazee.ai, vLLM, or any OpenAI-compatible endpoint)"
            echo "   6) Ollama    (local models running on this machine)"
            echo ""
            read -p "   Your choices: " PROVIDER_CHOICES

            for c in $PROVIDER_CHOICES; do
                case "$c" in
                    1) SELECTED_PROVIDERS+=("anthropic") ;;
                    2) SELECTED_PROVIDERS+=("google")    ;;
                    3) SELECTED_PROVIDERS+=("openai")    ;;
                    4) SELECTED_PROVIDERS+=("mistral")   ;;
                    5) SELECTED_PROVIDERS+=("custom")    ;;
                    6) SELECTED_PROVIDERS+=("ollama")    ;;
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
                    custom)
                        echo ""
                        echo "   ℹ️  Custom endpoint setup"
                        echo "   ⚠️  Adding custom models will completely overwrite config/litellm/config.yaml"
                        echo "      and config/models/custom/models.json when the setup completes."
                        echo ""
                        echo "   Three identifiers are required for each endpoint:"
                        echo "   • Local ID    — a short identifier used inside this project to route requests (no spaces)"
                        echo "   • Menu label  — the name shown in translation/evaluation menus (name as you like)"
                        echo "   • Remote ID   — the model name sent to YOUR endpoint (check provider docs)"

                        CUSTOM_IDX=0
                        while true; do
                            CUSTOM_IDX=$((CUSTOM_IDX + 1))
                            echo ""
                            echo "   ── Custom endpoint #${CUSTOM_IDX} ──"
                            local_id=""
                            while true; do
                                read -p "   Local ID (e.g. amazee-claude-haiku, no spaces): " local_id
                                if [ -z "$local_id" ]; then
                                    echo "   ⚠️  Local ID cannot be empty. Please try again."
                                elif [[ "$local_id" =~ [[:space:]] ]]; then
                                    echo "   ⚠️  Local ID must not contain spaces. Use hyphens instead (e.g. amazee-claude-haiku)."
                                else
                                    break
                                fi
                            done
                            read -p "   Menu label (e.g. amazee.ai - Claude 3.5 Haiku) [${local_id}]: " display_name
                            display_name="${display_name:-$local_id}"
                            remote_id=""
                            while true; do
                                read -p "   Remote model ID sent to endpoint (e.g. claude-3-5-haiku): " remote_id
                                [ -n "$remote_id" ] && break
                                echo "   ⚠️  Remote model ID cannot be empty. Please try again."
                            done
                            base_url=""
                            while true; do
                                read -p "   Base URL (e.g. https://llm.us104.amazee.ai/v1): " base_url
                                [ -n "$base_url" ] && break
                                echo "   ⚠️  Base URL cannot be empty. Please try again."
                            done
                            api_key=""
                            while true; do
                                read -s -p "   API Key: " api_key
                                echo ""
                                [ -n "$api_key" ] && break
                                echo "   ⚠️  API Key cannot be empty. Please try again."
                            done

                            CUSTOM_MODEL_NAMES+=("$local_id")
                            CUSTOM_MODEL_DISPLAYS+=("$display_name")
                            CUSTOM_REMOTE_MODEL_IDS+=("$remote_id")
                            CUSTOM_LLM_BASE_URLS+=("$base_url")
                            CUSTOM_LLM_API_KEYS+=("$api_key")

                            echo "   ✅ Configured: ${display_name} (${local_id}) → ${base_url}"
                            echo ""
                            read -p "   Add another custom endpoint? [y/N]: " ADD_MORE
                            [[ "$ADD_MORE" =~ ^[Yy]$ ]] || break
                        done

                        echo ""
                        echo "   ℹ️  To add more custom endpoints later, edit the config files directly:"
                        echo "      • config/litellm/config.yaml   (LLM routing)"
                        echo "      • config/models/custom/models.json   (menu entries)"
                        echo "      • .env   (credentials)"
                        echo "      See: docs/8_multi_llm_support.md for details."
                        ;;



                    ollama)
                        echo ""
                        echo "   ℹ️  Ollama (local models) setup"
                        echo "   ⚠️  Adding Ollama models will completely overwrite config/litellm/config.yaml"
                        echo "      and config/models/custom/models.json when the setup completes."
                        echo ""
                        OLLAMA_BASE_URL="http://host.docker.internal:11434"
                        echo "   ✅ OLLAMA_BASE_URL set to: ${OLLAMA_BASE_URL}"
                        while true; do
                            read -p "   Model name(s), comma-separated (e.g. llama3.1,mistral): " OLLAMA_MODELS
                            [ -n "$OLLAMA_MODELS" ] && break
                            echo "   ⚠️  At least one model name is required. Please try again."
                        done
                        echo "   ℹ️  Ollama must be running on your host with OLLAMA_HOST=0.0.0.0"
                        if [[ "$(uname)" == "Linux" ]]; then
                            echo "   ⚠️  Linux detected: docker-compose.yml already includes extra_hosts for"
                            echo "       host.docker.internal — no manual change needed."
                        fi
                        ;;
                esac
            done

            # Gateway URL used by the app to reach the proxy
            LLM_BASE_URL="http://litellm:4000/v1"
            LLM_API_TOKEN=""

            # ── Deduplicate custom endpoint credentials ────────────────────
            # Multiple endpoints may share the same base URL + API key (e.g.
            # two models on the same amazee.ai instance). Build a deduplicated
            # list so .env does not contain redundant entries.
            for i in "${!CUSTOM_LLM_BASE_URLS[@]}"; do
                _url="${CUSTOM_LLM_BASE_URLS[$i]}"
                _key="${CUSTOM_LLM_API_KEYS[$i]}"
                _found=""
                for j in "${!DEDUP_URLS[@]}"; do
                    if [ "${DEDUP_URLS[$j]}" = "$_url" ] && [ "${DEDUP_KEYS[$j]}" = "$_key" ]; then
                        _found=$((j + 1))
                        break
                    fi
                done
                if [ -z "$_found" ]; then
                    DEDUP_URLS+=("$_url")
                    DEDUP_KEYS+=("$_key")
                    _found=${#DEDUP_URLS[@]}
                fi
                ENDPOINT_ENV_IDX+=("$_found")
            done

            # ── Generate LiteLLM config.yaml ───────────────────────────────
            section "📝 GENERATING LITELLM CONFIG"

            if [ ! -f "$LITELLM_EXAMPLE" ]; then
                echo "❌ Example config not found: config/litellm/config.example.yaml"
                echo "   Please ensure the repository is intact and try again."
                exit 1
            fi

            # Overwrite prompt if config.yaml already exists
            if [ -f "$LITELLM_CONFIG" ]; then
                # If the user entered custom/ollama data, warn them it will be lost if they skip
                HAS_CUSTOM_DATA=false
                for p in "${SELECTED_PROVIDERS[@]}"; do
                    [[ "$p" == "custom" || "$p" == "ollama" ]] && HAS_CUSTOM_DATA=true && break
                done
                if [ "$HAS_CUSTOM_DATA" = true ]; then
                    echo "   ⚠️  config/litellm/config.yaml already exists."
                    echo "      If you do not overwrite, the custom model information you just entered will be discarded."
                    read -p "   Overwrite with your new settings? [Y/n]: " OW
                    OW="${OW:-Y}"
                else
                    read -p "   config/litellm/config.yaml already exists. Overwrite? [y/N]: " OW
                    OW="${OW:-N}"
                fi
                if [[ ! "$OW" =~ ^[Yy]$ ]]; then
                    echo "   ⏭️  Keeping existing config.yaml."
                    LITELLM_CONFIG=""   # signal: skip generation
                fi
            fi

            if [ -n "$LITELLM_CONFIG" ]; then
                {
                    echo "# LiteLLM Gateway Configuration"
                    echo "# Auto-generated by setup.sh on $(date '+%Y-%m-%d %H:%M')"
                    echo "# To add more models, edit this file or re-run bin/setup.sh."
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
                        custom)
                            # Generate one entry per custom endpoint
                            {
                                echo ""
                                echo "  # ---------------------------------------------------------------------------"
                                echo "  # Custom OpenAI-compatible endpoints"
                                echo "  # ---------------------------------------------------------------------------"
                                for i in "${!CUSTOM_MODEL_NAMES[@]}"; do
                                    local_idx=${ENDPOINT_ENV_IDX[$i]}
                                    cat << CUSTOM_ENTRY
  - model_name: ${CUSTOM_MODEL_NAMES[$i]}
    litellm_params:
      model: openai/${CUSTOM_REMOTE_MODEL_IDS[$i]}
      api_base: os.environ/CUSTOM_LLM_BASE_URL_${local_idx}
      api_key: os.environ/CUSTOM_LLM_API_KEY_${local_idx}
CUSTOM_ENTRY
                                done
                            } >> "$LITELLM_CONFIG"
                            ;;
                        ollama)
                            # Generate one entry per model name
                            IFS=',' read -ra OLLAMA_MODEL_LIST <<< "$OLLAMA_MODELS"
                            {
                                echo ""
                                echo "  # ---------------------------------------------------------------------------"
                                echo "  # Ollama (local models on the host machine)"
                                echo "  # ---------------------------------------------------------------------------"
                                for ollama_model in "${OLLAMA_MODEL_LIST[@]}"; do
                                    ollama_model="$(echo "$ollama_model" | xargs)"  # trim whitespace
                                    cat << OLLAMA_ENTRY
  - model_name: ${ollama_model}
    litellm_params:
      model: ollama/${ollama_model}
      api_base: os.environ/OLLAMA_BASE_URL
OLLAMA_ENTRY
                                done
                            } >> "$LITELLM_CONFIG"
                            ;;
                    esac
                done

                echo "   ✅ Written: config/litellm/config.yaml"
                echo ""
            fi

            # ── Generate custom models.json ────────────────────────────────
            GENERATE_CUSTOM_MODELS=true
            if [ ! -f "$MODELS_EXAMPLE" ]; then
                echo "   ⚠️  models.example.json not found — skipping custom models.json generation."
                GENERATE_CUSTOM_MODELS=false
            elif [ -f "$CUSTOM_MODELS" ]; then
                HAS_CUSTOM_DATA=false
                for p in "${SELECTED_PROVIDERS[@]}"; do
                    [[ "$p" == "custom" || "$p" == "ollama" ]] && HAS_CUSTOM_DATA=true && break
                done
                if [ "$HAS_CUSTOM_DATA" = true ]; then
                    echo "   ⚠️  config/models/custom/models.json already exists."
                    echo "      If you do not overwrite, the custom model information you just entered will be discarded."
                    read -p "   Overwrite with your new settings? [Y/n]: " OW_MODELS
                    OW_MODELS="${OW_MODELS:-Y}"
                else
                    read -p "   config/models/custom/models.json already exists. Overwrite? [y/N]: " OW_MODELS
                    OW_MODELS="${OW_MODELS:-N}"
                fi
                if [[ ! "$OW_MODELS" =~ ^[Yy]$ ]]; then
                    echo "   ⏭️  Keeping existing models.json."
                    GENERATE_CUSTOM_MODELS=false
                fi
            fi
            if [ "$GENERATE_CUSTOM_MODELS" = true ]; then
                PROVIDERS_ARG="${SELECTED_PROVIDERS[*]}"
                # Build pipe-separated strings for multiple custom endpoints
                # Use ${arr[@]+"${arr[@]}"} to safely handle empty arrays under set -u (bash 3.2)
                CUSTOM_NAMES_STR="$(IFS='|'; echo "${CUSTOM_MODEL_NAMES[@]+${CUSTOM_MODEL_NAMES[*]}}")"
                CUSTOM_DISPLAYS_STR="$(IFS='|'; echo "${CUSTOM_MODEL_DISPLAYS[@]+${CUSTOM_MODEL_DISPLAYS[*]}}")"
                python3 - "$PROVIDERS_ARG" "$MODELS_EXAMPLE" "$CUSTOM_MODELS" \
                    "$CUSTOM_NAMES_STR" "$OLLAMA_MODELS" "$CUSTOM_DISPLAYS_STR" << 'PYEOF'
import json, sys

providers_str, example_path, output_path = sys.argv[1], sys.argv[2], sys.argv[3]
custom_names_str = sys.argv[4] if len(sys.argv) > 4 else ""
ollama_models_str = sys.argv[5] if len(sys.argv) > 5 else ""
custom_displays_str = sys.argv[6] if len(sys.argv) > 6 else ""
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

# Custom OpenAI-compatible endpoint model entries
if "custom" in providers and custom_names_str:
    names = custom_names_str.split("|")
    displays = custom_displays_str.split("|") if custom_displays_str else names
    for i, name in enumerate(names):
        if name:
            display = displays[i] if i < len(displays) else name
            selected.append({
                "id": name,
                "name": display or name,
                "is_dry_run": False,
            })

# Ollama model entries (one per model name)
if "ollama" in providers and ollama_models_str:
    for raw in ollama_models_str.split(","):
        model = raw.strip()
        if model:
            selected.append({
                "id": model,
                "name": f"Ollama \u2014 {model}",
                "is_dry_run": False,
            })

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
            if [ ${#CUSTOM_MODEL_NAMES[@]} -gt 0 ]; then
                info "Custom:       ${#CUSTOM_MODEL_NAMES[@]} endpoint(s)"
                for i in "${!CUSTOM_MODEL_NAMES[@]}"; do
                    info "              • ${CUSTOM_MODEL_DISPLAYS[$i]} (${CUSTOM_MODEL_NAMES[$i]})"
                done
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
    for i in "${!DEDUP_URLS[@]}"; do
        local_idx=$((i + 1))
        PROVIDER_KEYS_BLOCK="${PROVIDER_KEYS_BLOCK}CUSTOM_LLM_BASE_URL_${local_idx}=${DEDUP_URLS[$i]}
"
        PROVIDER_KEYS_BLOCK="${PROVIDER_KEYS_BLOCK}CUSTOM_LLM_API_KEY_${local_idx}=${DEDUP_KEYS[$i]}
"
    done
    if [ -n "$OLLAMA_BASE_URL" ]; then
        PROVIDER_KEYS_BLOCK="${PROVIDER_KEYS_BLOCK}OLLAMA_BASE_URL=${OLLAMA_BASE_URL}
"
    fi

    cat > "$ENV_FILE" << ENVEOF
# .env file — Generated by setup.sh on $(date '+%Y-%m-%d %H:%M')
# Setup mode: ${SETUP_MODE}

# --- LLM Connection -----------------------------------------------------------
LLM_BASE_URL=${LLM_BASE_URL}
LLM_API_TOKEN=${LLM_API_TOKEN}

# --- Provider API Keys (LiteLLM Gateway) --------------------------------------
# Only the keys for your selected providers are populated below.
ENVEOF

    # Use printf to safely write user-supplied values (API keys/URLs may contain
    # double-quotes which would cause "unexpected EOF" inside an unquoted heredoc)
    printf '%s\n' "${PROVIDER_KEYS_BLOCK}" >> "$ENV_FILE"

    cat >> "$ENV_FILE" << ENVEOF

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
ENVEOF


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
echo ""
# ── Offer to start Docker Compose now ──────────────────────────────────────────
echo "🐳 Would you like to start the project now?"
echo ""
COMPOSE_CMD="docker compose up -d"
echo "   This will run: ${COMPOSE_CMD}"
echo ""
read -p "   Run it now? [Y/n]: " START_NOW
START_NOW="${START_NOW:-Y}"
if [[ "$START_NOW" =~ ^[Yy]$ ]]; then
    echo ""
    echo "🚀 Starting..."
    $COMPOSE_CMD
    echo ""
    echo "✅ Done! Containers are starting up."
else
    echo ""
    echo "📢 When ready, start the project with:"
    echo "     ${COMPOSE_CMD}"
fi
echo ""
