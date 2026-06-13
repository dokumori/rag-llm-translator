import os
import re
import argparse
from typing import Any, Dict, List

# Regex for BCP-47-style language codes
_LANGCODE_RE = re.compile(r'^[a-z]{2,3}(-[a-zA-Z0-9]{2,4})?$')


def langcode(value: str) -> str:
    """Argparse ``type=`` validator for BCP-47-style language codes.

    Accepted patterns: ja, en, fra, pt-br, zh-Hant
    Rejected patterns: jpa, 12345, with_rag, a, ''

    Raises:
        argparse.ArgumentTypeError: if *value* does not match the expected pattern.
    """
    if not _LANGCODE_RE.match(value):
        raise argparse.ArgumentTypeError(
            f"Invalid language code '{value}'. "
            "Expected format: 2-3 lowercase letters, optionally followed by "
            "a hyphen and 2-4 alphanumerics (e.g. ja, pt-br, zh-Hant)."
        )
    return value


def optional_langcode(value: str) -> str:
    """Like :func:`langcode`, but also accepts the empty string ``""``.

    Use this for optional ``--lang`` arguments that default to ``""`` and
    mean "no language filter", while still rejecting clearly invalid values
    like ``"jpa"`` or ``"12345"``.
    """
    if value == "":
        return value
    return langcode(value)


def find_po_files(directory: str, recursive: bool = False) -> List[str]:
    """
    Finds all .po files in the specified directory, handling case-insensitive extensions
    across all platforms (e.g., .po, .PO, .Po, .pO).
    
    Args:
        directory: The directory to search in.
        recursive: Whether to search subdirectories recursively.
        
    Returns:
        A sorted list of unique absolute paths to .po files.
    """
    found_files = []
    
    if recursive:
        for root, _, files in os.walk(directory):
            for file in files:
                if file.lower().endswith('.po'):
                    found_files.append(os.path.join(root, file))
    else:
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.is_file() and entry.name.lower().endswith('.po'):
                    found_files.append(entry.path)
                    
    return sorted(list(set(found_files)))


# ---------------------------------------------------------------------------
# O-series / reasoning-model detection
# ---------------------------------------------------------------------------

# OpenAI reasoning models (o1, o3, o4) and GPT-5 family require two special
# accommodations vs. standard chat models:
#   1. They reject temperature values other than 1 with a 400 error.
#   2. They use max_completion_tokens instead of max_tokens.
# We detect them by prefix match on the model ID.  LiteLLM does NOT translate
# these automatically, so we handle both explicitly.
_REASONING_MODEL_PREFIXES = ("o1", "o1-", "o3", "o3-", "o4", "o4-", "gpt-5")


def is_openai_reasoning_model(model_id: str) -> bool:
    """Return True if *model_id* identifies an OpenAI reasoning/o-series model."""
    return any(model_id.lower().startswith(p) for p in _REASONING_MODEL_PREFIXES)


def build_llm_call_kwargs(
    model_id: str,
    messages: List[Dict[str, Any]],
    max_tokens: int,
) -> Dict[str, Any]:
    """
    Build the ``**kwargs`` dict for ``openai.chat.completions.create``.

    Handles the two special cases for O-series reasoning models:
    - Omits ``temperature`` (they only accept the default value of 1).
    - Uses ``max_completion_tokens`` instead of ``max_tokens``.

    Args:
        model_id:   LLM model identifier string.
        messages:   The formatted messages list.
        max_tokens: Output token cap (sourced from request body or Config).

    Returns:
        A kwargs dict ready to be unpacked into ``client.chat.completions.create``.
    """
    reasoning = is_openai_reasoning_model(model_id)
    kwargs: Dict[str, Any] = {
        "model": model_id,
        "messages": messages,
    }
    if reasoning:
        kwargs["max_completion_tokens"] = max_tokens
    else:
        kwargs["max_tokens"] = max_tokens
        kwargs["temperature"] = 0
    return kwargs

