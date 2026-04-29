import sys
import logging
from collections import defaultdict
from typing import List, Optional, Dict, Any
from python_gpt_po.services.translation_service import TranslationService
from python_gpt_po.main import main

logger = logging.getLogger(__name__)

original_process_bulk = TranslationService._process_with_incremental_save_bulk


def patched_process_with_incremental_save_bulk(self, request):
    """
    Monkey-patch for TranslationService._process_with_incremental_save_bulk.

    The library's default implementation computes a single "most common context"
    per batch, which means a context-less entry (None) in the same batch as a
    context-ful one (e.g. "msgctxt8") incorrectly inherits that context.

    This patch pre-splits the request into per-context sub-requests and runs
    each through the original implementation independently, so every batch sent
    to the LLM is guaranteed to have a uniform (or absent) context.

    Entry order in the PO file is preserved because _process_batch writes
    directly to each entry object (not to an index-ordered list).
    """
    if not request.contexts or all(c is None for c in request.contexts):
        # No context information at all — safe to use the original path unchanged.
        logger.debug("run_gpt_po: no contexts present, using original bulk path")
        return original_process_bulk(self, request)

    all_same = len(set(request.contexts)) == 1

    if all_same:
        # All entries share the same context (or all are None) — no splitting needed.
        logger.debug("run_gpt_po: all entries share context '%s', using original bulk path", request.contexts[0])
        return original_process_bulk(self, request)

    # Mixed contexts: group entries by their context value so each sub-request
    # only contains entries with identical context.
    logger.info(
        "run_gpt_po: mixed contexts detected (%d entries). "
        "Splitting into per-context sub-requests to prevent context bleed.",
        len(request.texts)
    )

    # Build groups preserving original index
    groups: Dict[Any, List[int]] = defaultdict(list)
    for i, ctx in enumerate(request.contexts):
        groups[ctx].append(i)

    for ctx, indices in groups.items():
        sub_entries = [request.entries[i] for i in indices]
        sub_texts = [request.texts[i] for i in indices]
        sub_contexts = [request.contexts[i] for i in indices]  # all identical within group
        sub_plural = ([request.plural_metadata[i] for i in indices]
                      if request.plural_metadata else None)

        logger.info(
            "run_gpt_po: processing %d entries with context=%r",
            len(sub_texts), ctx
        )

        # Build a minimal TranslationRequest for this context group.
        # We reuse the same po_file reference so _process_batch writes directly
        # to the correct entry objects (it mutates entry.msgstr in-place).
        sub_request = type(request)(
            po_file=request.po_file,
            entries=sub_entries,
            texts=sub_texts,
            target_language=request.target_language,
            po_file_path=request.po_file_path,
            detail_language=request.detail_language,
            contexts=sub_contexts,
            plural_metadata=sub_plural,
        )

        original_process_bulk(self, sub_request)


# Apply the patch
TranslationService._process_with_incremental_save_bulk = patched_process_with_incremental_save_bulk

if __name__ == "__main__":
    sys.exit(main())
