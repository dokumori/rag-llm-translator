import os
import csv
import re
import argparse
import chromadb
import logging
from collections import defaultdict
from typing import List, Dict, Any, Tuple, Set, Optional

from core.config import Config
from infrastructure import get_chroma_client

logger = logging.getLogger(__name__)

# --- Configuration ---
CHROMA_HOST = Config.CHROMA_HOST
CHROMA_PORT = Config.CHROMA_PORT
COLLECTION_NAME = Config.TM_COLLECTION

# Minimum number of occurrences across the database for a term pair to be included.
MIN_OCCURRENCE_COUNT = 2


def is_substring_match(term_src: str, term_tgt: str, record_src: str, record_tgt: str) -> bool:
    """Returns True if the term pair appears (as a word boundary match) within the record."""
    if term_tgt not in record_tgt:
        return False
    pattern = r'\b' + re.escape(term_src) + r'\b'
    return bool(re.search(pattern, record_src, re.IGNORECASE))


# ---------------------------------------------------------------------------
# Phase helpers
# ---------------------------------------------------------------------------

def _phase1_identify_candidates(records: List[Tuple[str, dict]]) -> Dict:
    """
    Collects short (1–3 word) source/target pairs as glossary candidates.
    Returns {(src_lower, msgctxt): set of (original_src, target_str)}.
    """
    # Key: (src_lower, msgctxt), Value: set of (original_src, target_string)
    candidates: Dict = defaultdict(set)
    for src, meta in records:
        src = src.strip()
        tgt = str(meta.get('target', '')).strip()
        msgctxt = str(meta.get('msgctxt', '')).strip()
        if not src or not tgt:
            continue
        
        # Only consider short terms (1-3 words) as glossary headers
        word_count = len(src.split())
        if 0 < word_count <= 3 and len(src) < 50:
            # Key includes msgctxt so the same English term in different Drupal
            # contexts is kept as a separate glossary entry.
            candidates[(src.lower(), msgctxt)].add((src, tgt))
    return candidates


def _phase2_count_frequencies(
    candidates: Dict,
    records: List[Tuple[str, dict]],
) -> List[Dict]:
    """
    Counts how many records each candidate term pair appears in.
    Returns only terms that meet MIN_OCCURRENCE_COUNT.
    """
    # Optimization: Pre-load records for scanning
    scan_records = [
        (src.strip(), str(meta.get('target', '')).strip())
        for src, meta in records
    ]

    # tallied_terms = list of dicts with counts
    tallied_terms: List[Dict] = []
    for (src_key, msgctxt), variations in candidates.items():
        for (head_src, head_tgt) in variations:
            count = sum(
                1 for r_src, r_tgt in scan_records
                if is_substring_match(head_src, head_tgt, r_src, r_tgt)
            )
            # Keep if it appears more than once (based on MIN_OCCURRENCE_COUNT)
            if count >= MIN_OCCURRENCE_COUNT:
                tallied_terms.append({
                    'key': src_key,
                    'msgctxt': msgctxt,
                    'src': head_src,
                    'tgt': head_tgt,
                    'count': count,
                })
    return tallied_terms


def _phase3_prune_superstrings(tallied_terms: List[Dict]) -> Dict:
    """
    Removes compound terms when their base term already subsumes them
    (e.g. suppresses 'Action ID' when 'Action' is present with matching target root).
    Pruning is scoped to the same msgctxt group.
    Returns a {(src_key, msgctxt): [term_dict, ...]} map of surviving terms.
    """
    # Sort by length of English source (shortest first) to prioritize base terms.
    tallied_terms.sort(key=lambda x: len(x['src']))

    ignore_indices: Set[int] = set()
    for i, short in enumerate(tallied_terms):
        if i in ignore_indices:
            continue
        for j in range(i + 1, len(tallied_terms)):
            if j in ignore_indices:
                continue
            long = tallied_terms[j]
            
            # Only prune within the same msgctxt group
            if short['msgctxt'] != long['msgctxt']:
                continue
                
            # Check if English 'Action' is in 'Action ID'
            if is_substring_match(short['src'], short['tgt'], long['src'], long['tgt']):
                # If 'Action' -> 'アクション' covers 'Action ID' -> 'アクションID'
                # We suppress 'Action ID'
                ignore_indices.add(j)

    # Group surviving terms by their (key, msgctxt) pair
    final_map: Dict = defaultdict(list)
    for i, item in enumerate(tallied_terms):
        if i not in ignore_indices:
            final_map[(item['key'], item['msgctxt'])].append(item)
    return final_map


def _phase4_write_csv(
    final_map: Dict,
    langcode: str,
    output_dir: str,
) -> None:
    """Writes surviving glossary entries to a CSV, sorted by source then context."""
    output_path = os.path.join(output_dir, f"db_derived_glossary_{langcode}.csv")

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Source', 'Context', 'Target', 'Total Occurrences', 'Consistency', 'Alternatives'])

        # Sort alphabetically by Source, then by Context
        for key in sorted(final_map.keys(), key=lambda k: (k[0], k[1])):
            variations = final_map[key]
            src_key, msgctxt = key

            # Pick the variation with the highest count as the "Primary"
            primary = max(variations, key=lambda x: x['count'])
            total_count = sum(v['count'] for v in variations)
            
            # Consistency of the Primary translation
            consistency = (primary['count'] / total_count) * 100 if total_count > 0 else 0
            
            # List alternatives
            alts = [f"{v['tgt']} ({v['count']})" for v in variations if v['tgt'] != primary['tgt']]

            writer.writerow([
                primary['src'],     # e.g., "Browser"
                msgctxt,            # e.g., "Visibility" or ""
                primary['tgt'],     # e.g., "ブラウザ"
                primary['count'],   # Count for THIS specific translation
                # Consistency relative to other variations
                f"{consistency:.1f}%",
                "; ".join(alts),    # e.g., "ブラウザー (5)"
            ])

    logger.info(f"  💾 [{langcode}] Wrote {len(final_map)} entries to {output_path}")


# ---------------------------------------------------------------------------
# Public orchestrator
# ---------------------------------------------------------------------------

def extract_glossary_for_language(
    records: List[Tuple[str, dict]],
    langcode: str,
    output_dir: str,
) -> None:
    """
    Runs the 4-phase glossary extraction pipeline for a single language.

    Args:
        records:    List of (document_text, metadata_dict) tuples for the given langcode.
        langcode:   The language code (e.g. 'ja', 'it', 'nl').
        output_dir: Directory to write the output CSV into.
    """
    logger.info(f"  🌐 [{langcode}] Processing {len(records)} records...")

    candidates = _phase1_identify_candidates(records)
    logger.info(
        f"  🔍 [{langcode}] Found {len(candidates)} unique (term, context) pairs. "
        "Phase 2: Counting Frequencies..."
    )

    tallied_terms = _phase2_count_frequencies(candidates, records)
    logger.info(f"  📉 [{langcode}] Phase 3: Pruning Superstrings...")

    final_map = _phase3_prune_superstrings(tallied_terms)

    _phase4_write_csv(final_map, langcode, output_dir)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract a draft glossary from the Translation Memory in ChromaDB.")
    parser.add_argument("--lang", default=None,
                        help="Optional: extract for a single language only (e.g. 'ja'). "
                             "Without this flag, all languages in the database are processed.")
    args = parser.parse_args()

    client = get_chroma_client()

    try:
        collection = client.get_collection(name=COLLECTION_NAME)
    except Exception as e:
        logger.error(f"❌ Could not find collection '{COLLECTION_NAME}': {e}")
        return

    logger.info(f"📂 Accessing collection '{COLLECTION_NAME}'...")

    results = collection.get(include=['documents', 'metadatas'])
    docs = results.get('documents', [])
    metas = results.get('metadatas', [])

    if not docs or not metas:
        logger.warning("❌ No data found.")
        return

    logger.info(f"✅ Retrieved {len(docs)} records. Partitioning by language...")

    lang_groups: Dict = defaultdict(list)
    for i in range(len(docs)):
        langcode = str(metas[i].get('langcode', 'unknown')).strip()
        lang_groups[langcode].append((docs[i], metas[i]))

    if args.lang:
        if args.lang not in lang_groups:
            logger.error(
                f"❌ Language '{args.lang}' not found in database. "
                f"Available: {sorted(lang_groups.keys())}"
            )
            return
        lang_groups = {args.lang: lang_groups[args.lang]}

    logger.info(f"🌍 Found {len(lang_groups)} language(s): {sorted(lang_groups.keys())}")

    RAG_ANALYSIS_DIR = os.environ.get("RAG_ANALYSIS_DIR", "/app/data/rag-analysis")
    logger.info(f"🔧 Config: RAG_ANALYSIS_DIR = {RAG_ANALYSIS_DIR}")
    os.makedirs(RAG_ANALYSIS_DIR, exist_ok=True)

    for langcode in sorted(lang_groups.keys()):
        extract_glossary_for_language(
            records=lang_groups[langcode],
            langcode=langcode,
            output_dir=RAG_ANALYSIS_DIR,
        )

    # Summary log
    is_docker = os.path.exists('//.dockerenv')
    output_files = [f"db_derived_glossary_{lc}.csv" for lc in sorted(lang_groups.keys())]

    if is_docker:
        logger.info("🎉 Done! Since you are running in Docker, files are available on your host at:")
        for fname in output_files:
            logger.info(f"   📄 ./data/rag-analysis/{fname}")
    else:
        logger.info(f"🎉 Done! Glossary files saved to '{RAG_ANALYSIS_DIR}':")
        for fname in output_files:
            logger.info(f"   📄 {fname}")


if __name__ == "__main__":
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        level=logging.INFO,
    )
    main()
