#!/bin/bash
# bin/lib/env_helpers.sh
#
# Shared helper functions for .env file manipulation.
# Sourced by setup_post_processing.sh (and testable via BATS).
#
# Expected globals (must be set before calling):
#   ENV_FILE     — path to the .env file
#   PROJECT_ROOT — path to the project root directory
#   LANG_KEYS    — indexed array of language codes  (used by _build_plugin_lines)
#   LANG_VALS    — indexed array of plugin values    (used by _build_plugin_lines)

# Builds POST_PROCESS_PLUGINS_<LANG>=<value> lines from LANG_KEYS/LANG_VALS.
# Outputs the lines to stdout (no trailing newline after the last line).
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

# Patches the .env file: strips old post-processing config and appends a
# new block with the given enabled value and plugin lines.
#
# Usage: _patch_env <enabled_value> <plugin_lines>
#   enabled_value — "true" or "false"
#   plugin_lines  — output from _build_plugin_lines (may be empty)
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

  # Remove trailing blank lines (cross-platform: python3 is already a project dependency)
  python3 -c "
import sys
path = sys.argv[1]
with open(path) as f:
    content = f.read()
with open(path, 'w') as f:
    f.write(content.rstrip('\n') + '\n')
" "$tmp_file"

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
