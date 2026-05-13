"""
po_translator.py — Lightweight .po file translation driver.

Uses polib (for .po I/O) and the openai SDK (for LLM calls) directly,
replacing the former gpt-po-translator subprocess approach.

Key design choices:
  - Entries are grouped by msgctxt before batching, so every batch sent to
    the LLM contains only entries that share a single context value.
    This prevents context bleed natively without any monkey-patching.
  - Plural entries are expanded into one slot per plural form (following the
    approach used by gpt-po-translator).  Each slot is sent to the LLM as a
    plain string, avoiding fragile nested-JSON structures.  The number of
    required forms is read from the file's ``Plural-Forms`` header first,
    with a language-code look-up table as the fallback.
  - The .po file is saved incrementally after each batch, preserving partial
    progress if a crash or API error occurs mid-file.
  - The payload format is a clean JSON list of {"text": ..., "context": ...}
    dicts — a contract we own end-to-end, so the RAG proxy needs no
    format-specific regex workarounds.

Attribution:
  The plural-form expansion strategy and the ``_PLURAL_COUNTS`` language table
  are adapted from **gpt-po-translator** (pescheckit/python-gpt-po).

  Source:
    - https://github.com/pescheckit/python-gpt-po/blob/09b961539d4e53ab8a34aee6bd2eb9613e6df619/python_gpt_po/utils/plural_form_helpers.py
    - https://github.com/pescheckit/python-gpt-po/blob/09b961539d4e53ab8a34aee6bd2eb9613e6df619/python_gpt_po/services/translation_service.py
  License: MIT
  Copyright (c) 2026 Bram Mittendorff <bram@pescheck.io>
"""

import json
import logging
import re
import time
from typing import Dict, List, NamedTuple, Optional, Tuple

import polib
from openai import OpenAI
from core.token_tracker import TokenTracker

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Plural form count look-up table (ISO 639-1 base code → nplurals).
# Adapted from gpt-po-translator's plural_form_helpers.py (MIT, Bram Mittendorff).
#
# Keys are always the two-letter ISO 639-1 base code.  Any BCP-47 subtag
# (region, script, variant) is stripped before the look-up, so a single
# entry covers all regional variants automatically:
#   "pt"  covers  pt-BR, pt-PT, pt …
#   "en"  covers  en-GB, en-US, en-AU …
#   "zh"  covers  zh-Hans, zh-Hant, zh-TW …
#
# The .po file's own ``Plural-Forms`` header is always consulted first and
# takes priority over this table when present.
# ---------------------------------------------------------------------------
_PLURAL_COUNTS: Dict[str, int] = {
    # 1 form — no grammatical plural
    "ja": 1, "ko": 1, "zh": 1, "vi": 1, "th": 1, "id": 1, "ms": 1,
    # 2 forms — singular / plural (most European languages)
    "en": 2, "de": 2, "fr": 2, "es": 2, "it": 2, "pt": 2, "nl": 2,
    "sv": 2, "da": 2, "no": 2, "fi": 2, "et": 2, "el": 2, "he": 2,
    "hu": 2, "tr": 2, "bg": 2, "ca": 2,
    # 3 forms — Slavic and Baltic languages
    "ru": 3, "uk": 3, "pl": 3, "cs": 3, "hr": 3, "sr": 3, "sk": 3,
    "lt": 3, "lv": 3, "ro": 3,
    # 6 forms — Arabic
    "ar": 6,
}


class _Slot(NamedTuple):
    """One LLM translation unit (a singular entry or one plural form)."""
    text: str                    # source text to translate
    entry: object                # polib.POEntry
    form_index: Optional[int]   # None → singular; 0..N-1 → plural form index
    total_forms: Optional[int]  # None → singular; N → total plural forms for this entry


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def _get_plural_count(po: polib.POFile, lang_code: str) -> int:
    """
    Return the number of plural forms required by this .po file.

    Priority:
    1. Parse ``nplurals=N`` from the ``Plural-Forms`` metadata header.
    2. Strip any BCP-47 subtag (region, script, variant) from ``lang_code``
       and look up the resulting ISO 639-1 base code in ``_PLURAL_COUNTS``.
       This means a single entry handles all regional variants:
       ``pt`` matches ``pt-BR``, ``pt-PT``, ``pt``; ``en`` matches
       ``en-GB``, ``en-US``, etc.
    3. Default to 2 (the most common case).
    """
    plural_forms_header = (po.metadata or {}).get("Plural-Forms", "")
    if plural_forms_header:
        m = re.search(r"nplurals\s*=\s*(\d+)", plural_forms_header)
        if m:
            try:
                n = int(m.group(1))
                if 1 <= n <= 6:
                    return n
            except ValueError:
                pass

    # Strip region/script subtag: "pt-BR" → "pt", "zh_Hans" → "zh"
    base_lang = lang_code.lower().split("_")[0].split("-")[0]
    return _PLURAL_COUNTS.get(base_lang, 2)


def _expand_entry(entry: polib.POEntry, plural_count: int) -> List[_Slot]:
    """
    Convert one POEntry into one or more translation slots.

    Singular entries produce a single slot (``form_index=None``).
    Plural entries are expanded into ``plural_count`` slots:
      - form 0 uses ``msgid``       (the grammatical singular source)
      - forms 1..N-1 use ``msgid_plural`` (the grammatical plural source)
    """
    if entry.msgid_plural:
        return [
            _Slot(
                text=entry.msgid if i == 0 else entry.msgid_plural,
                entry=entry,
                form_index=i,
                total_forms=plural_count,
            )
            for i in range(plural_count)
        ]
    return [_Slot(text=entry.msgid, entry=entry, form_index=None, total_forms=None)]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def translate_po_file(
    file_path: str,
    model: str,
    target_lang: str,
    env: Dict[str, str],
    max_retries: int = 2,
    bulk_size: Optional[int] = None,
    tracker: Optional[TokenTracker] = None,
) -> bool:
    """
    Translates all untranslated (and fuzzy) entries in a .po file.

    Args:
        file_path:    Absolute path to the .po file to translate in-place.
        model:        LLM model ID to pass to the upstream API.
        target_lang:  BCP-47 language code (e.g. "ja", "nl").
        env:          Environment dict carrying OPENAI_API_KEY / OPENAI_BASE_URL.
        max_retries:  Number of retry attempts per batch on API failure.
        bulk_size:    Maximum slots per LLM request (note: plural entries expand
                      into multiple slots, so a single POEntry may consume N slots).
        tracker:      Optional TokenTracker to accumulate token usage across
                      all batches.  Pass None to skip tracking (default).

    Returns:
        True if all batches completed without fatal errors, False otherwise.
    """
    if bulk_size is None:
        bulk_size = int(env.get("BULK_SIZE", 15))

    try:
        po = polib.pofile(file_path)
    except Exception as exc:
        logger.error("❌ Failed to load PO file %s: %s", file_path, exc)
        return False

    # Filter to entries that still need translation
    target_entries = [e for e in po if not e.translated() or "fuzzy" in e.flags]
    if not target_entries:
        logger.info("✅ No untranslated entries in %s — nothing to do.", file_path)
        return True

    plural_count = _get_plural_count(po, target_lang)
    logger.debug("Plural form count for '%s': %d", target_lang, plural_count)

    client = OpenAI(
        api_key=env.get("OPENAI_API_KEY", "dummy"),
        base_url=env.get("OPENAI_BASE_URL"),
    )

    # Group entries by msgctxt so every batch is context-homogeneous.
    # Entries without a msgctxt are keyed on the empty string.
    groups: Dict[str, List[polib.POEntry]] = {}
    for entry in target_entries:
        ctx = entry.msgctxt or ""
        groups.setdefault(ctx, []).append(entry)

    logger.info(
        "🌐 Translating %d entries across %d context group(s) in %s",
        len(target_entries), len(groups), file_path,
    )

    all_ok = True
    for ctx, entries in groups.items():
        ctx_label = repr(ctx) if ctx else "<no context>"

        # Expand plural entries into individual form slots before batching.
        slots: List[_Slot] = []
        for entry in entries:
            slots.extend(_expand_entry(entry, plural_count))

        # Accumulate plural form translations across batches.
        # Keyed by id(entry) so different entries never collide.
        plural_acc: Dict[int, Dict[int, str]] = {}

        for batch_start in range(0, len(slots), bulk_size):
            batch = slots[batch_start : batch_start + bulk_size]
            logger.debug(
                "   ↳ Sending batch of %d slot(s) (context=%s)", len(batch), ctx_label
            )
            ok, translations = _process_batch(
                client, model, [s.text for s in batch], ctx, max_retries,
                tracker=tracker,
            )
            if not ok:
                logger.error(
                    "   ❌ Batch failed permanently (context=%s, start=%d)",
                    ctx_label, batch_start,
                )
                all_ok = False
                po.save()
                continue

            # Write translations back to entries
            for slot, translation in zip(batch, translations):
                entry = slot.entry
                if slot.form_index is None:
                    # Singular entry
                    entry.msgstr = translation
                    if "fuzzy" in entry.flags:
                        entry.flags.remove("fuzzy")
                else:
                    # Plural entry: accumulate forms, write when all collected
                    eid = id(entry)
                    plural_acc.setdefault(eid, {})[slot.form_index] = translation
                    if len(plural_acc[eid]) == slot.total_forms:
                        entry.msgstr_plural = dict(plural_acc.pop(eid))
                        entry.msgstr = ""  # polib ignores msgstr when msgstr_plural is set
                        if "fuzzy" in entry.flags:
                            entry.flags.remove("fuzzy")

            # Save incrementally after every batch to preserve partial progress
            po.save()

    return all_ok


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _process_batch(
    client: OpenAI,
    model: str,
    texts: List[str],
    ctx: str,
    max_retries: int,
    tracker: Optional[TokenTracker] = None,
) -> Tuple[bool, List[str]]:
    """
    Sends one batch of plain source strings to the LLM and returns translations.

    Every item is a flat string — plural entries have already been expanded into
    individual slots by the caller, so no nested arrays are needed here.

    Args:
        tracker: Optional TokenTracker.  If provided, ``response.usage`` is
                 recorded after every successful API call.

    Returns:
        (True, [translation, ...]) on success.
        (False, [])               after all retries are exhausted.
    """
    payload = [{"text": t, "context": ctx} for t in texts]
    n = len(texts)
    prompt = (
        f"Translate the following {n} texts. "
        "Return ONLY a JSON array of strings with EXACTLY "
        f"{n} elements — one translation per input, in the same order. "
        "Do NOT split a single input into multiple elements, even if it contains newlines. "
        "Do NOT add any text outside the JSON array.\n\n"
        f"Texts to translate:\n{json.dumps(payload, ensure_ascii=False)}"
    )
    messages = [{"role": "user", "content": prompt}]

    for attempt in range(max_retries + 1):
        # --- API call (retriable: network errors, rate limits, timeouts) ---
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0,
            )
            content = response.choices[0].message.content or ""
            logger.debug("Raw LLM response:\n%s", content)
            if tracker is not None:
                tracker.record(response.usage)
        except Exception as exc:
            logger.error(
                "   ⚠️  Batch attempt %d/%d failed: %s",
                attempt + 1, max_retries + 1, exc,
            )
            if attempt < max_retries:
                wait = 2 ** (attempt + 1)  # 2s, 4s
                logger.debug("   ⏳ Retrying in %ds...", wait)
                time.sleep(wait)
            continue

        # --- Parsing (retriable: count mismatches are stochastic — a retry may succeed) ---
        try:
            translations = _parse_translations(content, expected_count=len(texts))
            return True, translations
        except ValueError as exc:
            logger.warning(
                "   ⚠️  Parse failure (attempt %d/%d): %s | Raw response: %.300s",
                attempt + 1, max_retries + 1, exc, content,
            )
            if attempt < max_retries:
                wait = 2 ** (attempt + 1)  # 2s, 4s
                logger.debug("   ⏳ Retrying in %ds...", wait)
                time.sleep(wait)
            else:
                logger.error(
                    "   ❌ Parse failure (all retries exhausted): %s | Raw response: %.300s",
                    exc, content,
                )
                return False, []

    return False, []



def _parse_translations(content: str, expected_count: int) -> List[str]:
    """
    Extracts the JSON translation array from the LLM response content.

    Each element is expected to be a plain string.
    Raises ValueError if no valid array is found or the count doesn't match.

    Implementation note:
        Rather than using ``str.find("[")`` / ``str.rfind("]")`` to locate the
        array boundaries (which breaks when the LLM wraps the response in prose
        that itself contains square brackets), we use
        ``json.JSONDecoder.raw_decode``.  It scans forward from each ``[``
        character and stops at the *exact* closing bracket of the outermost
        array, correctly skipping any ``[`` / ``]`` that appear inside string
        values.  This makes parsing fully bracket-aware and resilient to:
          - Translated strings containing ``[`` or ``]`` (e.g. Markdown links,
            BBCode, placeholder syntax like ``[user]``)
          - LLM prose with square-bracket notation before or after the array
    """
    decoder = json.JSONDecoder()

    for i, ch in enumerate(content):
        if ch != "[":
            continue
        try:
            value, _ = decoder.raw_decode(content, i)
        except json.JSONDecodeError:
            continue  # not a valid JSON value starting here — keep scanning

        if not isinstance(value, list):
            continue  # found JSON but it's not an array — keep scanning

        got = len(value)
        if got > expected_count:
            # Lenient: model returned extra items (common with Haiku 3.5).
            # Trim the tail — the leading N items are the actual translations.
            extra = value[expected_count:]
            logger.warning(
                "   ⚠️  Model returned %d items for %d expected — trimming %d extra: %s",
                got, expected_count, got - expected_count,
                [repr(e)[:80] for e in extra],
            )
            value = value[:expected_count]
        elif got < expected_count:
            # Cannot fabricate missing translations — hard failure.
            raise ValueError(
                f"Expected {expected_count} translations, got {got} (too few to recover)"
            )

        return [str(t) for t in value]

    raise ValueError(f"No JSON array found in LLM response: {content[:200]!r}")
