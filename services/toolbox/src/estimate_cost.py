"""
estimate_cost.py — Pre-flight cost estimation for translation runs.

Counts untranslated entries in .po files, estimates token usage using a
character-based heuristic, and computes a cost range from model pricing
in models.yaml.  No API calls are made.

Output is one KEY=VALUE line per metric so bash can parse it without jq:

    STRINGS=1247
    BATCHES=84
    INPUT_TOKENS=42300
    OUTPUT_TOKENS_LOW=42300
    OUTPUT_TOKENS_HIGH=84600
    COST_LOW=1.23
    COST_HIGH=2.46
    HAS_PRICING=true

Usage (inside toolbox container):
    python3 /app/src/estimate_cost.py \\
        --input /app/po/input/ja \\
        --model claude-sonnet-4-6 \\
        --target-lang ja \\
        --bulk-size 15
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
from typing import Optional, Tuple

import polib

# Shared modules — available on PYTHONPATH=/app/src:/app/shared inside toolbox
from core.config import load_models_config
from core.token_tracker import build_price_table_from_config
from core.utils import find_po_files, langcode

# Reuse plural-expansion helpers from po_translator to stay consistent with the
# actual translation logic.  These are module-private by convention only; there
# is no access restriction in Python.
from po_translator import _expand_entry, _get_plural_count

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Estimation constants
# ---------------------------------------------------------------------------

# Average English characters per BPE token.  Real tokenisers average ~3.5–4.5;
# 4.0 is deliberately conservative so we don't underestimate costs.
CHARS_PER_TOKEN: float = 4.0

# Fixed per-batch token overhead (prompt + RAG context buffer + boilerplate).
#   System prompt:            ~1 500 chars  ÷ 4 ≈ 375 tokens
#   RAG context (typical):    ~800 chars    ÷ 4 ≈ 200 tokens
#   User-message boilerplate: ~400 chars    ÷ 4 ≈ 100 tokens
OVERHEAD_TOKENS_PER_BATCH: int = 375 + 200 + 100  # = 675

# JSON-payload wrapping overhead per slot: {"text": "...", "context": "..."}
# adds roughly 30 characters on top of the source text itself.
JSON_WRAP_CHARS_PER_SLOT: int = 30

# Output token multipliers for the cost range.
# Lower bound:  output ≈ input   (1:1 — translations are similar in length)
# Upper bound:  output ≈ 2× input (accounts for verbose languages + JSON array)
OUTPUT_MULTIPLIER_LOW: float = 1.0
OUTPUT_MULTIPLIER_HIGH: float = 2.0


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def count_and_estimate(
    input_dir: str,
    target_lang: str,
    bulk_size: int,
) -> Tuple[int, int, int]:
    """Count untranslated slots and estimate total input tokens.

    Args:
        input_dir:   Host-side directory that contains ``.po`` files.
        target_lang: BCP-47 language code (used for plural-form lookup).
        bulk_size:   Maximum slots per LLM batch request.

    Returns:
        (total_slots, total_batches, estimated_input_tokens)
        All three are 0 when the directory is empty or contains no work.
    """
    po_files = find_po_files(input_dir)
    if not po_files:
        return 0, 0, 0

    total_slots: int = 0
    total_source_chars: int = 0

    for po_path in po_files:
        try:
            po = polib.pofile(po_path)
        except Exception as exc:
            logger.warning("Skipping unreadable file %s: %s", po_path, exc)
            continue

        # Match the filter in po_translator.translate_po_file (line 182):
        # entries that are untranslated OR fuzzy still need processing.
        target_entries = [
            e for e in po if not e.translated() or "fuzzy" in e.flags
        ]
        if not target_entries:
            continue

        plural_count = _get_plural_count(po, target_lang)

        for entry in target_entries:
            slots = _expand_entry(entry, plural_count)
            total_slots += len(slots)
            for slot in slots:
                total_source_chars += len(slot.text) + JSON_WRAP_CHARS_PER_SLOT

    if total_slots == 0:
        return 0, 0, 0

    total_batches = math.ceil(total_slots / bulk_size)

    source_tokens = int(total_source_chars / CHARS_PER_TOKEN)
    overhead_tokens = total_batches * OVERHEAD_TOKENS_PER_BATCH
    estimated_input_tokens = source_tokens + overhead_tokens

    return total_slots, total_batches, estimated_input_tokens


def compute_cost_range(
    input_tokens: int,
    prompt_rate: Optional[float],
    completion_rate: Optional[float],
) -> Tuple[Optional[float], Optional[float]]:
    """Compute a (low, high) USD cost range for the given token estimate.

    Both rates must be present; if either is ``None`` this returns
    ``(None, None)`` so callers can display "N/A" cleanly.

    Args:
        input_tokens:    Estimated prompt-side token count.
        prompt_rate:     USD cost per 1 000 prompt tokens, or ``None``.
        completion_rate: USD cost per 1 000 completion tokens, or ``None``.

    Returns:
        ``(cost_low, cost_high)`` rounded to 4 decimal places,
        or ``(None, None)`` if pricing is unavailable.
    """
    if prompt_rate is None or completion_rate is None:
        return None, None

    output_tokens_low = int(input_tokens * OUTPUT_MULTIPLIER_LOW)
    output_tokens_high = int(input_tokens * OUTPUT_MULTIPLIER_HIGH)

    cost_low = (
        input_tokens / 1000 * prompt_rate
        + output_tokens_low / 1000 * completion_rate
    )
    cost_high = (
        input_tokens / 1000 * prompt_rate
        + output_tokens_high / 1000 * completion_rate
    )

    return round(cost_low, 4), round(cost_high, 4)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Estimate translation cost without making API calls."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Directory containing .po files to translate",
    )
    parser.add_argument(
        "--model",
        required=True,
        help="LLM model ID (must match an 'id' in models.yaml)",
    )
    parser.add_argument(
        "--target-lang",
        required=True,
        type=langcode,
        help="Target language BCP-47 code (e.g. ja, pt-br)",
    )
    parser.add_argument(
        "--bulk-size",
        type=int,
        default=15,
        help="Slots per batch (default: 15, matches BULK_SIZE in .env)",
    )
    args = parser.parse_args()

    total_slots, total_batches, input_tokens = count_and_estimate(
        args.input, args.target_lang, args.bulk_size
    )

    # Look up pricing from models.yaml via the shared config layer.
    prompt_rate: Optional[float] = None
    completion_rate: Optional[float] = None
    try:
        models_cfg = load_models_config()
        price_table = build_price_table_from_config(models_cfg)
        prompt_rate, completion_rate = price_table.get(args.model, (None, None))
    except Exception as exc:
        logger.warning("Could not load pricing: %s", exc)

    cost_low, cost_high = compute_cost_range(input_tokens, prompt_rate, completion_rate)
    has_pricing = cost_low is not None

    output_low = int(input_tokens * OUTPUT_MULTIPLIER_LOW)
    output_high = int(input_tokens * OUTPUT_MULTIPLIER_HIGH)

    # Print KEY=VALUE pairs for easy bash parsing (no jq dependency required).
    print(f"STRINGS={total_slots}")
    print(f"BATCHES={total_batches}")
    print(f"INPUT_TOKENS={input_tokens}")
    print(f"OUTPUT_TOKENS_LOW={output_low}")
    print(f"OUTPUT_TOKENS_HIGH={output_high}")
    print(f"COST_LOW={cost_low if cost_low is not None else 0}")
    print(f"COST_HIGH={cost_high if cost_high is not None else 0}")
    print(f"HAS_PRICING={'true' if has_pricing else 'false'}")


if __name__ == "__main__":
    main()
