#!/bin/bash
# bin/common.sh
#
# Shared path helpers and language selection utilities.
# Source this from other scripts: source "$(dirname "$0")/common.sh"
#
# All scripts MUST use these functions for language-aware path resolution
# instead of hardcoding paths. This ensures a single convention:
#   data/tm_source/{langcode}/
#   data/translations/input/{langcode}/
#   data/translations/output/{langcode}/
#   data/translations/eval/{langcode}/

# --- Base Directories ---
DATA_ROOT="${DATA_ROOT:-data}"
TM_SOURCE_ROOT="${DATA_ROOT}/tm_source"
TRANSLATIONS_ROOT="${DATA_ROOT}/translations"

# --- Path Helpers ---
# Each function takes a langcode as the first argument.

tm_source_dir()   { echo "${TM_SOURCE_ROOT}/$1"; }
glossary_path()   { echo "$(tm_source_dir "$1")/glossary.csv"; }
input_dir()       { echo "${TRANSLATIONS_ROOT}/input/$1"; }
output_dir()      { echo "${TRANSLATIONS_ROOT}/output/$1"; }
eval_dir()        { echo "${TRANSLATIONS_ROOT}/eval/$1"; }

# --- Language Discovery ---

# Discovers all non-hidden language subdirectories under base_dir.
# Returns bare langcodes, one per line. No file-content filtering.
#
# Usage: discover_lang_dirs <base_dir>
#   base_dir — parent directory containing lang subdirs (e.g. data/tm_source)
discover_lang_dirs() {
    local base_dir="$1"
    local lang
    for d in "$base_dir"/*/; do
        [ -d "$d" ] || continue
        lang=$(basename "$d")
        [[ "$lang" == .* ]] && continue
        echo "$lang"
    done
}

# Lists available language codes by scanning for subdirectories
# that contain at least one file matching the given extension.
#
# Usage: list_available_langs <base_dir> [extension]
#   base_dir — parent directory containing lang subdirs (e.g. data/tm_source)
#   extension — file extension filter (default: .po)
list_available_langs() {
    local base_dir="$1"
    local ext="${2:-.po}"

    for d in "$base_dir"/*/; do
        [ -d "$d" ] || continue
        local dir_name=$(basename "$d")
        # Ignore directories longer than 5 chars (e.g. 'with_rag', 'without_rag')
        # assuming the longest langcode would be something like pt-br
        [ ${#dir_name} -gt 5 ] && continue
        
        if find "$d" -maxdepth 2 -name "*${ext}" -print -quit 2>/dev/null | grep -q .; then
            echo "$dir_name"
        fi
    done
}

# Interactive language selector. Prints the chosen langcode to stdout.
# All prompts/messages go to stderr so stdout stays clean for capture.
#
# Usage: LANG_CODE=$(select_language "translation" "data/translations/input" ".po")
select_language() {
    local purpose="$1"   # e.g. "translation", "ingestion"
    local base_dir="$2"  # directory to scan for lang subdirs
    local ext="${3:-.po}" # file extension filter

    local langs=()
    while IFS= read -r l; do
        [ -n "$l" ] && langs+=("$l")
    done < <(list_available_langs "$base_dir" "$ext")

    if [ ${#langs[@]} -eq 0 ]; then
        echo "❌ No languages with *${ext} files found in ${base_dir}/" >&2
        return 1
    fi

    # Append the "all" option
    langs+=("all")

    echo "" >&2
    echo "Select target language for ${purpose}:" >&2
    local saved_ps3="$PS3"
    PS3="Enter the number of your choice: "

    select lang in "${langs[@]}"; do
        if [ -n "$lang" ]; then
            PS3="$saved_ps3"
            echo "$lang"
            return 0
        fi
        echo "❌ Invalid option. Please try again." >&2
    done
}

# --- Environment Loading ---
# Loads .env file if present, excluding UID/GID to avoid shell conflicts.
load_env() {
    if [ -f .env ]; then
        export $(grep -v '^#' .env | grep -vE '^(UID|GID)' | xargs)
    fi
}
