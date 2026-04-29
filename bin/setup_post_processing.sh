#!/bin/bash
# bin/setup_post_processing.sh
#
# Interactive setup for per-language post-processing plugins.
# Patches the existing .env file in-place.
# Safe to re-run — old post-processing config is always replaced.

set -e

# Ensure we are running from project root
cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"

# Source shared helpers
source "$(dirname "$0")/common.sh"

# ─── Pre-flight ──────────────────────────────────────────────────────
ENV_FILE="${PROJECT_ROOT}/.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "❌ .env file not found. Please run 'bash bin/initial_setup.sh' first."
  exit 1
fi

# ─── Step 1: Explain ─────────────────────────────────────────────────
echo ""
echo "===================================================================="
echo " ✨ Post-Processing Setup"
echo "===================================================================="
echo "Post-processing runs text-cleanup plugins on your translated .po"
echo "files (e.g. fixing spacing around Drupal variables, adding Japanese-"
echo "English spacing). Plugins are configured per language."
echo ""

# ─── Step 2: Enable / Disable ────────────────────────────────────────
read -p "Enable post-processing? (y/n) [default: y]: " ENABLE_PP
ENABLE_PP="${ENABLE_PP:-y}"

if [[ "$ENABLE_PP" =~ ^[Nn] ]]; then
  # Strip old config and set disabled
  _patch_env "false" ""
  echo ""
  echo "ℹ️  Post-processing disabled. To reconfigure later, re-run:"
  echo "    bash bin/setup_post_processing.sh"
  exit 0
fi

# ─── Step 3: Discover available plugins ──────────────────────────────
PLUGIN_DIR="${PROJECT_ROOT}/services/toolbox/src/plugins"
PLUGINS=()
PLUGIN_SOURCES=()

# Default plugins
if [ -d "${PLUGIN_DIR}/default" ]; then
  for f in "${PLUGIN_DIR}/default/"*.py; do
    [ -e "$f" ] || continue
    name=$(basename "$f" .py)
    [[ "$name" == "__init__" ]] && continue
    PLUGINS+=("$name")
    PLUGIN_SOURCES+=("default")
  done
fi

# Custom plugins
if [ -d "${PLUGIN_DIR}/custom" ]; then
  for f in "${PLUGIN_DIR}/custom/"*.py; do
    [ -e "$f" ] || continue
    name=$(basename "$f" .py)
    [[ "$name" == "__init__" ]] && continue
    PLUGINS+=("$name")
    PLUGIN_SOURCES+=("custom")
  done
fi

if [ ${#PLUGINS[@]} -eq 0 ]; then
  echo "⚠️  No plugins found in ${PLUGIN_DIR}/{default,custom}/."
  echo "   Create plugins first, then re-run this script."
  exit 1
fi

echo "Available plugins:"
for i in "${!PLUGINS[@]}"; do
  printf "  %d) %-40s (%s)\n" $((i + 1)) "${PLUGINS[$i]}" "${PLUGIN_SOURCES[$i]}"
done
echo ""

# ─── Step 4 & 5: Language selection + plugin assignment ──────────────

# Discover languages from input and tm_source directories
DETECTED_LANGS=()
for dir in "${TRANSLATIONS_ROOT}/input" "${TM_SOURCE_ROOT}"; do
  while IFS= read -r l; do
    # Avoid duplicates
    if [[ ! " ${DETECTED_LANGS[*]} " =~ " ${l} " ]]; then
      DETECTED_LANGS+=("$l")
    fi
  done < <(discover_lang_dirs "$dir" 2>/dev/null)
done

if [ ${#DETECTED_LANGS[@]} -gt 0 ]; then
  echo "Detected languages: ${DETECTED_LANGS[*]}"
else
  echo "ℹ️  No language directories detected."
fi
echo ""

# Collect per-language config
LANG_KEYS=()
LANG_VALS=()

# Pre-populate from existing .env
if [ -f "$ENV_FILE" ]; then
  while IFS='=' read -r key val || [[ -n "$key" ]]; do
    lang_upper="${key#POST_PROCESS_PLUGINS_}"
    lang_lower=$(echo "$lang_upper" | tr '[:upper:]' '[:lower:]' | tr '_' '-')
    # Clean up val (remove quotes if any)
    val="${val%\"}"
    val="${val#\"}"
    val="${val%\'}"
    val="${val#\'}"
    LANG_KEYS+=("$lang_lower")
    LANG_VALS+=("$val")
  done < <(grep -E '^POST_PROCESS_PLUGINS_[A-Z0-9_]+=' "$ENV_FILE" 2>/dev/null || true)
fi

while true; do
  echo "Configure plugins for which language?"
  echo "  • Enter a langcode (e.g. ja, es, pt-br)"
  echo "  • Type 'done' to finish"
  if [ ${#DETECTED_LANGS[@]} -gt 0 ]; then
    echo "  • Detected: ${DETECTED_LANGS[*]}"
  fi
  if [ ${#LANG_KEYS[@]} -gt 0 ]; then
    echo "  • Currently configured:"
    for i in "${!LANG_KEYS[@]}"; do
      echo "      - ${LANG_KEYS[$i]}: ${LANG_VALS[$i]:-(none)}"
    done
  fi
  read -p "> " CHOSEN_LANG

  # Finished
  [[ "$CHOSEN_LANG" == "done" || -z "$CHOSEN_LANG" ]] && break

  # Check if already configured
  current_val=""
  for i in "${!LANG_KEYS[@]}"; do
    if [[ "${LANG_KEYS[$i]}" == "$CHOSEN_LANG" ]]; then
      current_val="${LANG_VALS[$i]}"
      break
    fi
  done

  echo ""
  if [ -n "$current_val" ]; then
    echo "Currently selected for '${CHOSEN_LANG}': $current_val"
    echo "Select plugins for '${CHOSEN_LANG}' (comma-separated numbers in order of execution, 'none' to clear, or press Enter to keep current):"
    echo "⚠️  Note: Execution order matters. Plugins will run in the exact order you list them."
  else
    echo "Select plugins for '${CHOSEN_LANG}' (comma-separated numbers in order of execution, or 'none'):"
    echo "⚠️  Note: Execution order matters. Plugins will run in the exact order you list them."
  fi
  
  for i in "${!PLUGINS[@]}"; do
    printf "  %d) %s\n" $((i + 1)) "${PLUGINS[$i]}"
  done
  read -p "> " SELECTION

  if [[ -z "$SELECTION" && -n "$current_val" ]]; then
    echo "  → Keeping current configuration for '${CHOSEN_LANG}'"
    echo ""
    continue
  fi

  if [[ "$SELECTION" == "none" ]]; then
    # Explicit opt-out: empty value
    found=false
    for i in "${!LANG_KEYS[@]}"; do
      if [[ "${LANG_KEYS[$i]}" == "$CHOSEN_LANG" ]]; then
        LANG_VALS[$i]=""
        found=true
        break
      fi
    done
    if [ "$found" = false ]; then
      LANG_KEYS+=("$CHOSEN_LANG")
      LANG_VALS+=("")
    fi
    echo "  → No plugins for '${CHOSEN_LANG}'"
  else
    # Parse comma-separated numbers
    SELECTED_NAMES=()
    IFS=',' read -ra NUMS <<< "$SELECTION"
    for num in "${NUMS[@]}"; do
      num=$(echo "$num" | tr -d ' ')
      idx=$((num - 1))
      if [ "$idx" -ge 0 ] && [ "$idx" -lt "${#PLUGINS[@]}" ]; then
        SELECTED_NAMES+=("${PLUGINS[$idx]}")
      else
        echo "  ⚠️  Ignoring invalid number: $num"
      fi
    done

    if [ ${#SELECTED_NAMES[@]} -gt 0 ]; then
      PLUGIN_LIST=$(IFS=','; echo "${SELECTED_NAMES[*]}")
      found=false
      for i in "${!LANG_KEYS[@]}"; do
        if [[ "${LANG_KEYS[$i]}" == "$CHOSEN_LANG" ]]; then
          LANG_VALS[$i]="$PLUGIN_LIST"
          found=true
          break
        fi
      done
      if [ "$found" = false ]; then
        LANG_KEYS+=("$CHOSEN_LANG")
        LANG_VALS+=("$PLUGIN_LIST")
      fi
      # Normalise for display
      ENV_KEY="POST_PROCESS_PLUGINS_$(echo "$CHOSEN_LANG" | tr '[:lower:]' '[:upper:]' | tr '-' '_')"
      echo "  → ${ENV_KEY}=${PLUGIN_LIST}"
    else
      echo "  ⚠️  No valid plugins selected for '${CHOSEN_LANG}'. Skipping."
    fi
  fi
  echo ""
done

if [ ${#LANG_KEYS[@]} -eq 0 ]; then
  echo ""
  echo "⚠️  No languages configured. Post-processing will be enabled but"
  echo "   no plugins will run until you add POST_PROCESS_PLUGINS_<LANG>"
  echo "   variables to .env."
fi

# ─── Step 6: Patch .env ──────────────────────────────────────────────
_build_plugin_lines() {
  local lines=""
  for i in "${!LANG_KEYS[@]}"; do
    local lang="${LANG_KEYS[$i]}"
    local val="${LANG_VALS[$i]}"
    local env_key="POST_PROCESS_PLUGINS_$(echo "$lang" | tr '[:lower:]' '[:upper:]' | tr '-' '_')"
    lines+="${env_key}=${val}"$'\n'
  done
  echo -n "$lines"
}

_patch_env() {
  local enabled_value="$1"
  local plugin_lines="$2"

  # Create a temp file for the new .env
  local tmp_file
  tmp_file=$(mktemp "${PROJECT_ROOT}/.env.tmp.XXXXXX")

  # Copy all lines except old post-processing config
  while IFS= read -r line || [[ -n "$line" ]]; do
    # Skip old post-processing lines (both active and commented from template)
    case "$line" in
      POST_PROCESSING_ENABLED=*) continue ;;
      POST_PROCESS_PLUGINS=*) continue ;;
      POST_PROCESS_PLUGINS_*=*) continue ;;
      "# --- Post-Processing"*) continue ;;
      "#   bash bin/setup_post_processing.sh"*) continue ;;
      "# To configure post-processing"*) continue ;;
      "# Or uncomment and edit manually"*) continue ;;
      "# POST_PROCESS_PLUGINS_"*) continue ;;
      "# See docs/2_post_processing.md"*) continue ;;
      "# ----"*) continue ;;
      "#"*) ;; # keep other comments
    esac
    echo "$line" >> "$tmp_file"
  done < "$ENV_FILE"

  # Remove trailing blank lines
  sed -i '' -e :a -e '/^\n*$/{$d;N;ba' -e '}' "$tmp_file" 2>/dev/null || true

  # Append post-processing block
  {
    echo ""
    echo "# --- Post-Processing (configured by setup_post_processing.sh) ---"
    echo "POST_PROCESSING_ENABLED=${enabled_value}"
    if [ -n "$plugin_lines" ]; then
      echo -n "$plugin_lines"
    fi
  } >> "$tmp_file"

  # Replace original
  mv "$tmp_file" "$ENV_FILE"
}

PLUGIN_LINES=$(_build_plugin_lines)
_patch_env "true" "$PLUGIN_LINES"

echo ""
echo "===================================================================="
echo " ✅ Post-processing configured. Changes written to .env"
echo "===================================================================="
echo ""

# Show summary
echo "POST_PROCESSING_ENABLED=true"
for i in "${!LANG_KEYS[@]}"; do
  lang="${LANG_KEYS[$i]}"
  val="${LANG_VALS[$i]}"
  env_key="POST_PROCESS_PLUGINS_$(echo "$lang" | tr '[:lower:]' '[:upper:]' | tr '-' '_')"
  echo "${env_key}=${val}"
done

echo ""
echo "To reconfigure, re-run: bash bin/setup_post_processing.sh"
echo ""

echo "🔄 Reloading Docker containers to apply new configuration..."
docker compose up -d
