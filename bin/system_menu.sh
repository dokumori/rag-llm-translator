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

# Ignore Ctrl+C in the menu itself so the loop stays alive.
# Use ':' (no-op), NOT '' (SIG_IGN) — SIG_IGN is inherited by children
# and cannot be overridden, which would break child scripts' own traps.
trap ':' INT

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
GREEN="\033[32m"
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

# Added as part of the status check.
# Returns 0 if any langcode subdirectory under data/translations/eval/ contains
# both with_rag/ and without_rag/ subdirectories (required for [E] Evaluate)
_has_eval_data() {
    local eval_base="${TRANSLATIONS_ROOT}/eval"
    [ -d "$eval_base" ] || return 1
    for d in "$eval_base"/*/; do
        [ -d "$d" ] || continue
        [ -d "${d}with_rag" ] && [ -d "${d}without_rag" ] && return 0
    done
    return 1
}

# ── Status Refresh ────────────────────────────────────────────────────────────
# Added as part of the status check.
# Called once per menu render. Sets global boolean string variables ("true"/"false")
# consumed by both the dashboard and per-option badge logic.
# Docker-level checks (layer 2) are skipped when prerequisites aren't met,
# keeping the menu fast when the stack is down.
_refresh_status() {
    # Layer 1: fast host-level checks (no Docker involvement)
    HAS_ENV=false;    _has_env        && HAS_ENV=true
    DOCKER_OK=false;  _docker_running && DOCKER_OK=true
    HAS_TM=false;     _has_tm_data    && HAS_TM=true
    HAS_INPUT=false;  _has_input_po   && HAS_INPUT=true
    HAS_EVAL=false;   _has_eval_data  && HAS_EVAL=true

    # Layer 2: container-level checks (only when Docker is reachable)
    STACK_OK=false
    CHROMA_OK=false
    CHROMA_COUNT="?"
    if [ "$HAS_ENV" = true ] && [ "$DOCKER_OK" = true ]; then
        _stack_healthy && STACK_OK=true
        if [ "$STACK_OK" = true ]; then
            local count
            count=$(docker compose exec -T toolbox python3 -c "
import os, chromadb
host = os.environ.get('CHROMA_HOST', 'localhost')
port = int(os.environ.get('CHROMA_PORT', 8000))
c = chromadb.HttpClient(host=host, port=port)
print(len(c.list_collections()))
" 2>/dev/null || echo "0")
            CHROMA_COUNT="$count"
            [ "${count:-0}" -gt 0 ] 2>/dev/null && CHROMA_OK=true
        fi
    fi
}

# ── Menu Item Renderer ────────────────────────────────────────────────────────
# Added as part of the status check.
# Renders one option line, with cyan key when ready or dimmed key + hint when not.
#
# Arguments:
#   $1 — key letter (e.g. "S")
#   $2 — "true" if the option is ready to use, any other value to dim it
#   $3 — label text
#   $4 — description text
#   $5 — (optional) hint shown in yellow when dimmed
_menu_item() {
    local key="$1" ready="$2" label="$3" desc="$4" hint="${5:-}"
    if [ "$ready" = true ]; then
        printf "    ${CYAN}%s)${RESET} %s — %s\n" "$key" "$label" "$desc"
    elif [ -n "$hint" ]; then
        printf "    ${DIM}%s) %s — %s${RESET}  ${YELLOW}%s${RESET}\n" "$key" "$label" "$desc" "$hint"
    else
        printf "    ${DIM}%s) %s — %s${RESET}\n" "$key" "$label" "$desc"
    fi
}

# ── Menu Rendering ────────────────────────────────────────────────────────────
_render_menu() {
    _refresh_status

    echo ""
    echo -e "${BOLD}════════════════════════════════════════════════════${RESET}"
    echo -e "${BOLD}  RAG-LLM Translator — System Menu${RESET}"
    echo -e "${BOLD}════════════════════════════════════════════════════${RESET}"

    # ── Compact status dashboard ──────────────────────────────────────────────
    echo ""
    local env_badge docker_badge stack_badge chroma_badge

    if [ "$HAS_ENV" = true ]; then
        env_badge="${GREEN}✅${RESET}"
    else
        env_badge="${YELLOW}❌ run [S]${RESET}"
    fi

    if [ "$HAS_ENV" = false ]; then
        docker_badge="${DIM}—${RESET}"
        stack_badge="${DIM}—${RESET}"
        chroma_badge="${DIM}—${RESET}"
    elif [ "$DOCKER_OK" = false ]; then
        docker_badge="${YELLOW}❌ start Docker${RESET}"
        stack_badge="${DIM}—${RESET}"
        chroma_badge="${DIM}—${RESET}"
    elif [ "$STACK_OK" = false ]; then
        docker_badge="${GREEN}✅${RESET}"
        stack_badge="${YELLOW}❌ run: docker compose up -d${RESET}"
        chroma_badge="${DIM}—${RESET}"
    else
        docker_badge="${GREEN}✅${RESET}"
        stack_badge="${GREEN}✅${RESET}"
        if [ "$CHROMA_OK" = true ]; then
            chroma_badge="${GREEN}${CHROMA_COUNT} collection(s)${RESET}"
        else
            chroma_badge="${YELLOW}0 collections — run [I]${RESET}"
        fi
    fi

    echo -e "  .env: ${env_badge}  │  Docker: ${docker_badge}  │  Stack: ${stack_badge}  │  ChromaDB: ${chroma_badge}"

    # ── Menu options ──────────────────────────────────────────────────────────
    local stack_hint=""
    [ "$STACK_OK" = false ] && stack_hint="needs stack"

    echo ""
    echo -e "  ${BOLD}Getting Started${RESET}"
    _menu_item "S" true "Setup                         " "Configure LLM, API keys, and .env"
    _menu_item "D" true "Download demo data            " "Fetch sample data for Japanese"

    echo ""
    echo -e "  ${BOLD}Context (RAG)${RESET}"
    _menu_item "I" "$STACK_OK" "Ingest TM / Glossary          " "Load translation memory into ChromaDB" "$stack_hint"
    _menu_item "B" "$STACK_OK" "Backup or restore context data" "Manage ChromaDB snapshots" "$stack_hint"

    echo ""
    echo -e "  ${BOLD}Translate${RESET}"
    local t_ready=false t_hint=""
    if [ "$STACK_OK" = false ]; then
        t_hint="needs stack"
    elif [ "$CHROMA_OK" = false ]; then
        t_hint="run [I] to ingest first"
    elif [ "$HAS_INPUT" = false ]; then
        t_hint="no input .po files found"
    else
        t_ready=true
    fi
    _menu_item "T" "$t_ready" "Translate                     " "Run the translation pipeline" "$t_hint"

    echo ""
    echo -e "  ${BOLD}Evaluate & Tune${RESET}"
    local e_ready=false e_hint=""
    if [ "$STACK_OK" = false ]; then
        e_hint="needs stack"
    elif [ "$HAS_EVAL" = false ]; then
        e_hint="place files in data/translations/eval/<lang>/with_rag & without_rag"
    else
        e_ready=true
    fi
    _menu_item "E" "$e_ready" "Evaluate translation quality  " "LLM-as-a-Judge blind test" "$e_hint"
    _menu_item "A" "$STACK_OK" "Analyse RAG matching          " "Generate RAG performance report" "$stack_hint"

    echo ""
    echo -e "  ${BOLD}Configuration${RESET}"
    local env_hint=""
    [ "$HAS_ENV" = false ] && env_hint="run [S] Setup first"
    _menu_item "P" "$HAS_ENV" "Post-processing config        " "Enable/disable per-language plugins" "$env_hint"
    _menu_item "M" "$STACK_OK" "Model switch                  " "Change the sentence-transformer model" "$stack_hint"

    echo ""
    echo -e "  ${BOLD}Development${RESET}"
    _menu_item "X" true "eXecute tests                 " "Run the test suite"

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

# ── Option M: Model Switch helper ─────────────────────────────────────────────
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
        s|S)
            bash "$SCRIPT_DIR/setup.sh"
            # Reload env so subsequent status checks reflect new .env
            if [ -f .env ]; then load_env; fi
            _post_run_pause
            echo ""
            echo -e "${BOLD}════════════════════════════════════════════════════${RESET}"
            ;;

        d|D)
            bash "$SCRIPT_DIR/demo_prep.sh"
            _post_run_pause
            echo ""
            echo -e "${BOLD}════════════════════════════════════════════════════${RESET}"
            ;;

        # ── Context (RAG) ──────────────────────────────────────────────────
        i|I)
            if [ "$STACK_OK" = false ]; then
                echo ""
                echo -e "  ${YELLOW}⚠️  Docker stack must be running. Start with: docker compose up -d${RESET}"
                sleep 1.5
                continue
            fi
            echo ""
            echo "  ────────────────────────────────────────────────────"
            echo -e "  ${BOLD}📦 ChromaDB Overview (current state)${RESET}"
            echo "  ────────────────────────────────────────────────────"
            db_overview=
            if db_overview=$(docker compose exec -T toolbox python3 /app/src/check_db.py 2>/dev/null); then
                echo "$db_overview" | sed 's/^/     /'
            else
                echo -e "  ${YELLOW}⚠️  Could not retrieve DB overview (is the stack running?).${RESET}"
            fi
            echo "  ────────────────────────────────────────────────────"
            echo ""
            if _preflight \
"Place your translation memory (.po) and glossary (.csv) files under:
  data/tm_source/<langcode>/   (e.g. data/tm_source/ja/)

The Docker stack must be running (docker compose up -d).
📖 See: README.md §3 \"Place the files\" and docs/1_architecture.md"; then
                bash "$SCRIPT_DIR/ingest.sh"
                echo ""
                echo "  ────────────────────────────────────────────────────"
                echo -e "  ${BOLD}📦 ChromaDB Overview (post-ingest)${RESET}"
                echo "  ────────────────────────────────────────────────────"
                if db_overview=$(docker compose exec -T toolbox python3 /app/src/check_db.py 2>/dev/null); then
                    echo "$db_overview" | sed 's/^/     /'
                else
                    echo -e "  ${YELLOW}⚠️  Could not retrieve DB overview (is the stack running?).${RESET}"
                fi
                echo "  ────────────────────────────────────────────────────"
                _post_run_pause
                echo ""
                echo -e "${BOLD}════════════════════════════════════════════════════${RESET}"
            else
                clear
            fi
            ;;

        b|B)
            if [ "$STACK_OK" = false ]; then
                echo ""
                echo -e "  ${YELLOW}⚠️  Docker stack must be running. Start with: docker compose up -d${RESET}"
                sleep 1.5
                continue
            fi
            bash "$SCRIPT_DIR/manage-backup.sh"
            _post_run_pause
            echo ""
            echo -e "${BOLD}════════════════════════════════════════════════════${RESET}"
            ;;

        # ── Translate ──────────────────────────────────────────────────────
        t|T)
            if [ "$STACK_OK" = false ]; then
                echo ""
                echo -e "  ${YELLOW}⚠️  Docker stack must be running. Start with: docker compose up -d${RESET}"
                sleep 1.5
                continue
            elif [ "$CHROMA_OK" = false ]; then
                echo ""
                echo -e "  ${YELLOW}⚠️  No data ingested yet. Run [I] Ingest first.${RESET}"
                sleep 1.5
                continue
            elif [ "$HAS_INPUT" = false ]; then
                echo ""
                echo -e "  ${YELLOW}⚠️  No input .po files found. Place files in data/translations/input/<lang>/${RESET}"
                sleep 1.5
                continue
            fi
            if _preflight \
"Place untranslated .po files under:
  data/translations/input/<langcode>/   (e.g. data/translations/input/ja/)

Ensure you have already ingested TM/glossary data ([I] Ingest).
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
        e|E)
            if [ "$STACK_OK" = false ]; then
                echo ""
                echo -e "  ${YELLOW}⚠️  Docker stack must be running. Start with: docker compose up -d${RESET}"
                sleep 1.5
                continue
            elif [ "$HAS_EVAL" = false ]; then
                echo ""
                echo -e "  ${YELLOW}⚠️  Eval files not found. Place .po files under data/translations/eval/<lang>/with_rag/ and without_rag/${RESET}"
                sleep 1.5
                continue
            fi
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

        a|A)
            if [ "$STACK_OK" = false ]; then
                echo ""
                echo -e "  ${YELLOW}⚠️  Docker stack must be running. Start with: docker compose up -d${RESET}"
                sleep 1.5
                continue
            fi
            if _preflight \
"You must have run at least one translation ([T] Translate) so that
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
        p|P)
            if [ "$HAS_ENV" = false ]; then
                echo ""
                echo -e "  ${YELLOW}⚠️  No .env file found. Run [S] Setup first.${RESET}"
                sleep 1.5
                continue
            fi
            bash "$SCRIPT_DIR/setup_post_processing.sh"
            _post_run_pause
            echo ""
            echo -e "${BOLD}════════════════════════════════════════════════════${RESET}"
            ;;

        m|M)
            if [ "$STACK_OK" = false ]; then
                echo ""
                echo -e "  ${YELLOW}⚠️  Docker stack must be running. Start with: docker compose up -d${RESET}"
                sleep 1.5
                continue
            fi
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
        x|X)
            echo ""
            read -rp "  Include integration tests? (requires Docker stack) [y/N]: " run_integ
            run_integ="${run_integ:-N}"
            if [[ "$run_integ" =~ ^[Yy]$ ]]; then
                bash "$SCRIPT_DIR/run_tests.sh" --run-integration
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
            echo -e "  ${YELLOW}❌ Invalid choice: '${choice}'. Please enter S, D, I, B, T, E, A, P, M, X, or q.${RESET}"
            sleep 1
            ;;
    esac
done
