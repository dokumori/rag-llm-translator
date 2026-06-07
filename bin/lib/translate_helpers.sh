#!/bin/bash
# bin/lib/translate_helpers.sh
#
# Shared helper functions for translation script.
# Sourced by bin/translate.sh (and testable via BATS).

# Converts a model name to a filesystem-safe slug.
# Pure function — returns via stdout; safe to use with BATS `run`.
#
# Arguments:
#   $1 — selected_model (e.g. "Claude 3.5 Haiku", "gpt-4o")
#   $2 — is_dry_run ("true" or "false")
#
# Examples:
#   _compute_model_slug "BAAI/bge-large-en-v1.5" "false" → "baai-bge-large-en-v1-5"
#   _compute_model_slug "Claude 3.5 Haiku"       "false" → "claude-3-5-haiku"
#   _compute_model_slug "anything"               "true"  → "dry-run"
_compute_model_slug() {
    local selected_model="$1"
    local is_dry_run="$2"
    if [ "$is_dry_run" = "true" ]; then
        echo "dry-run"
    else
        echo "$selected_model" \
            | tr '[:upper:]' '[:lower:]' \
            | sed 's/[^a-z0-9]/-/g' \
            | sed 's/-\{2,\}/-/g' \
            | sed 's/^-//;s/-$//'
    fi
}
