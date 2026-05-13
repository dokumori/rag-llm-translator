#!/bin/bash
# bin/system_menu.sh
#
# Central system menu for the RAG-LLM Translator project.
# Provides a looping, status-aware CLI dashboard that groups all
# bin/ scripts by workflow lifecycle and guides users through
# preparation steps before each command.
#
# Usage:
#   bash bin/system_menu.sh

# ── Setup ─────────────────────────────────────────────────────────────────────
# Do NOT use set -e here: child scripts may exit non-zero and we want to catch
# that gracefully without killing the menu loop.
set +e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

source "$SCRIPT_DIR/common.sh"

# Load .env if present (provides EMBEDDING_MODEL_NAME etc. for status checks)
if [ -f .env ]; then
    load_env
fi

# ── Colours ───────────────────────────────────────────────────────────────────
BOLD="\033[1m"
DIM="\033[2m"
YELLOW="\033[33m"
CYAN="\033[36m"
RESET="\033[0m"

# ── Status Detection ──────────────────────────────────────────────────────────
# Returns 0 if .env exists, 1 otherwise
_has_env() { [ -f "$PROJECT_ROOT/.env" ]; }

# Returns 0 if Docker daemon is reachable
_docker_running() { docker info &>/dev/null 2>&1; }

# Returns 0 if rag-proxy container is healthy
_stack_healthy() {
    local status
    status=$(docker inspect --format='{{.State.Health.Status}}' rag-proxy 2>/dev/null || echo "missing")
    [ "$status" = "healthy" ]
}

# Returns 0 if ChromaDB has at least one collection
_chroma_has_collections() {
    local count
    count=$(docker compose exec -T toolbox python3 -c "
import os, chromadb
host = os.environ.get('CHROMA_HOST', 'localhost')
port = int(os.environ.get('CHROMA_PORT', 8000))
c = chromadb.HttpClient(host=host, port=port)
print(len(c.list_collections()))
" 2>/dev/null || echo "0")
    [ "$count" -gt 0 ] 2>/dev/null
}

# Returns 0 if any langcode subdirectory exists under data/tm_source/
_has_tm_data() {
    local found=false
    for d in "$PROJECT_ROOT/data/tm_source"/*/; do
        [ -d "$d" ] && found=true && break
    done
    [ "$found" = true ]
}

# Returns 0 if any .po file exists under data/translations/input/
_has_input_po() {
    find "$PROJECT_ROOT/data/translations/input" -name "*.po" -print -quit 2>/dev/null | grep -q .
}

# ── Status Messages ───────────────────────────────────────────────────────────
# Builds an array of warning/info messages using short-circuit logic.
# Only the most actionable checks are shown — deeper checks are skipped
# when a prerequisite problem is already detected.
_collect_status_messages() {
    STATUS_MESSAGES=()

    if ! _has_env; then
        STATUS_MESSAGES+=("⚠️  No .env file found. Run option 1 to get started.")
        return  # skip all further checks — nothing will work without .env
    fi

    if ! _docker_running; then
        STATUS_MESSAGES+=("⚠️  Docker is not running. Start Docker Desktop and try again.")
        return
    fi

    if ! _stack_healthy; then
        STATUS_MESSAGES+=("ℹ️  Docker stack is not running. Start with: docker compose up -d")
        return  # skip collection check — toolbox isn't reachable
    fi

    if ! _chroma_has_collections; then
        STATUS_MESSAGES+=("⚠️  ChromaDB has no collections. Run option 3 to ingest your TM/glossary.")
    fi

    if ! _has_tm_data; then
        STATUS_MESSAGES+=("ℹ️  No TM/glossary source data found in data/tm_source/. Run option 2 for demo data.")
    fi

    if ! _has_input_po; then
        STATUS_MESSAGES+=("ℹ️  No input .po files found. Place files in data/translations/input/<lang>/")
    fi
}

# ── Menu Rendering ────────────────────────────────────────────────────────────
_render_menu() {
    echo ""
    echo -e "${BOLD}════════════════════════════════════════════════════${RESET}"
    echo -e "${BOLD}  RAG-LLM Translator — System Menu${RESET}"
    echo -e "${BOLD}════════════════════════════════════════════════════${RESET}"

    # Status messages
    _collect_status_messages
    if [ ${#STATUS_MESSAGES[@]} -gt 0 ]; then
        echo ""
        for msg in "${STATUS_MESSAGES[@]}"; do
            echo -e "  ${YELLOW}${msg}${RESET}"
        done
    fi

    echo ""
    echo -e "  ${BOLD}Getting Started${RESET}"
    echo -e "    ${CYAN}1)${RESET} Initial setup                  — Configure LLM, API keys, and .env"
    echo -e "    ${CYAN}2)${RESET} Download demo data             — Fetch sample data for Japanese"
    echo ""
    echo -e "  ${BOLD}Context (RAG)${RESET}"
    echo -e "    ${CYAN}3)${RESET} Ingest TM / Glossary           — Load translation memory into ChromaDB"
    echo -e "    ${CYAN}4)${RESET} Backup or restore context data — Manage ChromaDB snapshots"
    echo ""
    echo -e "  ${BOLD}Translate${RESET}"
    echo -e "    ${CYAN}5)${RESET} Translate                      — Run the translation pipeline"
    echo ""
    echo -e "  ${BOLD}Evaluate & Tune${RESET}"
    echo -e "    ${CYAN}6)${RESET} Evaluate translation quality   — LLM-as-a-Judge blind test"
    echo -e "    ${CYAN}7)${RESET} Analyse RAG matching           — Generate RAG performance report"
    echo ""
    echo -e "  ${BOLD}Configuration${RESET}"
    echo -e "    ${CYAN}8)${RESET} Configure post-processing      — Enable/disable per-language plugins"
    echo -e "    ${CYAN}9)${RESET} Switch embedding model         — Change the sentence-transformer model"
    echo ""
    echo -e "  ${BOLD}Development${RESET}"
    echo -e "   ${CYAN}10)${RESET} Run tests                      — Execute the test suite"
    echo ""
    echo -e "    ${DIM}q) Quit${RESET}"
    echo ""
    echo -e "${BOLD}════════════════════════════════════════════════════${RESET}"
}

# ── Pre-flight Help Gate ──────────────────────────────────────────────────────
# Shows preparation instructions and a Y/n confirmation.
# Returns 0 if user confirms, 1 if user declines.
_preflight() {
    local message="$1"
    echo ""
    echo "  ────────────────────────────────────────────────────"
    echo -e "  ${BOLD}📋 Before you proceed:${RESET}"
    # Print each line of the message with consistent indentation
    while IFS= read -r line; do
        echo "     $line"
    done <<< "$message"
    echo "  ────────────────────────────────────────────────────"
    echo ""
    read -rp "  Ready to proceed? [Y/n]: " ready
    ready="${ready:-Y}"
    if [[ ! "$ready" =~ ^[Yy]$ ]]; then
        echo ""
        echo "  ↩️  Cancelled. Returning to menu..."
        return 1
    fi
    return 0
}

# ── Post-run separator ────────────────────────────────────────────────────────
# Called after a script has run. Does NOT clear the screen so users can
# scroll up to reference previous output.
_post_run_pause() {
    echo ""
    read -rp "  Press Enter to return to menu..." _ignored
}

# ── Option 9: Model Switch helper ─────────────────────────────────────────────
_prompt_model_name() {
    echo ""
    local current_model="${EMBEDDING_MODEL_NAME:-}"
    if [ -n "$current_model" ]; then
        echo -e "  Current model: ${DIM}${current_model}${RESET}"
    fi
    read -rp "  Enter new model name (e.g. BAAI/bge-base-en-v1.5): " new_model
    if [ -z "$new_model" ]; then
        echo "  ❌ No model name entered. Returning to menu."
        return 1
    fi
    MENU_MODEL_ARG="$new_model"
    return 0
}

# ── Main Loop ─────────────────────────────────────────────────────────────────
while true; do
    _render_menu
    read -rp "  Enter your choice: " choice

    case "$choice" in

        # ── Getting Started ────────────────────────────────────────────────
        1)
            bash "$SCRIPT_DIR/initial_setup.sh"
            # Reload env so subsequent status checks reflect new .env
            if [ -f .env ]; then load_env; fi
            _post_run_pause
            echo ""
            echo -e "${BOLD}════════════════════════════════════════════════════${RESET}"
            ;;

        2)
            bash "$SCRIPT_DIR/demo_prep.sh"
            _post_run_pause
            echo ""
            echo -e "${BOLD}════════════════════════════════════════════════════${RESET}"
            ;;

        # ── Context (RAG) ──────────────────────────────────────────────────
        3)
            if _preflight \
"Place your translation memory (.po) and glossary (.csv) files under:
  data/tm_source/<langcode>/   (e.g. data/tm_source/ja/)

The Docker stack must be running (docker compose up -d).
📖 See: README.md §3 \"Place the files\" and docs/1_architecture.md"; then
                bash "$SCRIPT_DIR/ingest.sh"
                _post_run_pause
                echo ""
                echo -e "${BOLD}════════════════════════════════════════════════════${RESET}"
            else
                clear
            fi
            ;;

        4)
            bash "$SCRIPT_DIR/manage-backup.sh"
            _post_run_pause
            echo ""
            echo -e "${BOLD}════════════════════════════════════════════════════${RESET}"
            ;;

        # ── Translate ──────────────────────────────────────────────────────
        5)
            if _preflight \
"Place untranslated .po files under:
  data/translations/input/<langcode>/   (e.g. data/translations/input/ja/)

Ensure you have already ingested TM/glossary data (option 3).
📖 See: README.md §6 \"Translate!\""; then
                bash "$SCRIPT_DIR/translate.sh"
                _post_run_pause
                echo ""
                echo -e "${BOLD}════════════════════════════════════════════════════${RESET}"
            else
                clear
            fi
            ;;

        # ── Evaluate & Tune ────────────────────────────────────────────────
        6)
            if _preflight \
"Place translated .po files for comparison under:
  data/translations/eval/<langcode>/with_rag/
  data/translations/eval/<langcode>/without_rag/

Each directory must contain exactly one .po file.
📖 See: docs/5_translation_evaluation.md"; then
                bash "$SCRIPT_DIR/eval_quality.sh"
                _post_run_pause
                echo ""
                echo -e "${BOLD}════════════════════════════════════════════════════${RESET}"
            else
                clear
            fi
            ;;

        7)
            if _preflight \
"You must have run at least one translation (option 5) so that
rag-proxy has produced traffic logs to analyse.
📖 See: docs/3_RAG_performance_analysis.md"; then
                bash "$SCRIPT_DIR/analyse.sh"
                _post_run_pause
                echo ""
                echo -e "${BOLD}════════════════════════════════════════════════════${RESET}"
            else
                clear
            fi
            ;;

        # ── Configuration ──────────────────────────────────────────────────
        8)
            bash "$SCRIPT_DIR/setup_post_processing.sh"
            _post_run_pause
            echo ""
            echo -e "${BOLD}════════════════════════════════════════════════════${RESET}"
            ;;

        9)
            if _preflight \
"Switching models will wipe all ChromaDB collections.
You will need to re-ingest all data afterwards.
📖 See: docs/7_embedding_model.md"; then
                if _prompt_model_name; then
                    bash "$SCRIPT_DIR/switch-embedding-model.sh" "$MENU_MODEL_ARG"
                    if [ -f .env ]; then load_env; fi
                    _post_run_pause
                    echo ""
                    echo -e "${BOLD}════════════════════════════════════════════════════${RESET}"
                else
                    clear
                fi
            else
                clear
            fi
            ;;

        # ── Development ────────────────────────────────────────────────────
        10)
            echo ""
            read -rp "  Include integration tests? (requires Docker stack) [y/N]: " run_integ
            run_integ="${run_integ:-N}"
            if [[ "$run_integ" =~ ^[Yy]$ ]]; then
                bash "$SCRIPT_DIR/run_tests.sh" --integration
            else
                bash "$SCRIPT_DIR/run_tests.sh"
            fi
            _post_run_pause
            echo ""
            echo -e "${BOLD}════════════════════════════════════════════════════${RESET}"
            ;;

        # ── Quit ───────────────────────────────────────────────────────────
        q|Q)
            echo ""
            echo "  Goodbye!"
            echo ""
            exit 0
            ;;

        # ── Invalid ────────────────────────────────────────────────────────
        *)
            echo ""
            echo -e "  ${YELLOW}❌ Invalid choice: '${choice}'. Please enter 1–10 or q.${RESET}"
            sleep 1
            ;;
    esac
done
