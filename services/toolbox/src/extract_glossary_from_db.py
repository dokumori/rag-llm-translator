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

# --- Logging Configuration ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
CHROMA_HOST = Config.CHROMA_HOST
CHROMA_PORT = Config.CHROMA_PORT
COLLECTION_NAME = Config.TM_COLLECTION


def is_substring_match(term_src: str, term_tgt: str, record_src: str, record_tgt: str) -> bool:
    """
    Checks if the term pair exists within the record.
    """
    # 1. Check Target (simple substring)
    if term_tgt not in record_tgt:
        return False

    # 2. Check English Source (Word Boundary is critical)
    pattern = r'\b' + re.escape(term_src) + r'\b'
    if re.search(pattern, record_src, re.IGNORECASE):
        return True

    return False


def extract_glossary_for_language(
    records: List[Tuple[str, dict]],
    langcode: str,
    output_dir: str
) -> None:
    """
    Runs the 4-phase glossary extraction pipeline for a single language.

    Args:
        records: List of (document_text, metadata_dict) tuples, all for the same langcode.
        langcode: The language code (e.g. 'ja', 'it', 'nl').
        output_dir: Directory to write the output CSV into.
    """
    logger.info(f"  🌐 [{langcode}] Processing {len(records)} records...")

    # --- PHASE 1: Identify Candidates (All Variations) ---
    # Key: (src_lower, msgctxt), Value: set of (original_src, target_string)
    candidates = defaultdict(set)

    for src, meta in records:
        src = src.strip()
        tgt = str(meta.get('target', '')).strip()
        msgctxt = str(meta.get('msgctxt', '')).strip()

        if not src or not tgt:
            continue

        # Only consider short terms (1-3 words) as glossary headers
        word_count = len(src.split())
        if 0 < word_count <= 3 and len(src) < 50:
            src_lower = src.lower()
            # Key includes msgctxt so same English term with different contexts stays separate
            candidates[(src_lower, msgctxt)].add((src, tgt))

    logger.info(
        f"  🔍 [{langcode}] Found {len(candidates)} unique (term, context) pairs. Phase 2: Counting Frequencies...")

    # --- PHASE 2: Global Frequency Scan ---
    # We count how often EACH variation appears in the full database for THIS language

    # Optimization: Pre-load records for scanning
    scan_records = []
    for src, meta in records:
        d_src = src.strip()
        d_tgt = str(meta.get('target', '')).strip()
        scan_records.append((d_src, d_tgt))

    # tallied_terms = list of dicts with counts
    tallied_terms = []

    for (src_key, msgctxt), variations in candidates.items():
        for (head_src, head_tgt) in variations:
            count = 0
            for r_src, r_tgt in scan_records:
                if is_substring_match(head_src, head_tgt, r_src, r_tgt):
                    count += 1

            # Keep if it appears more than once
            if count > 1:
                tallied_terms.append({
                    'key': src_key,
                    'msgctxt': msgctxt,
                    'src': head_src,
                    'tgt': head_tgt,
                    'count': count
                })

    logger.info(f"  📉 [{langcode}] Phase 3: Pruning Superstrings...")

    # --- PHASE 3: Pruning (Removing 'Action ID' if 'Action' exists) ---
    # We only prune if the Source matches (substring) AND the Target matches (substring).

    final_map = defaultdict(list)

    # Sort by length of English source (shortest first) to prioritize base terms
    tallied_terms.sort(key=lambda x: len(x['src']))

    ignore_indices = set()

    for i in range(len(tallied_terms)):
        if i in ignore_indices:
            continue
        short = tallied_terms[i]

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

    # --- PHASE 4: Aggregation by (English Term, msgctxt) ---
    # Group surviving terms by their (key, msgctxt) pair
    for i, item in enumerate(tallied_terms):
        if i not in ignore_indices:
            final_map[(item['key'], item['msgctxt'])].append(item)

    output_path = os.path.join(output_dir, f"db_derived_glossary_{langcode}.csv")

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(
            ['Source', 'Context', 'Target', 'Total Occurrences', 'Consistency', 'Alternatives'])

        # Sort alphabetically by Source, then by Context
        sorted_keys = sorted(final_map.keys(), key=lambda k: (k[0], k[1]))

        for key in sorted_keys:
            variations = final_map[key]
            src_key, msgctxt = key

            # Pick the variation with the highest count as the "Primary"
            primary = max(variations, key=lambda x: x['count'])
            total_count = sum(v['count'] for v in variations)

            # Consistency of the Primary translation
            consistency = (primary['count'] / total_count) * \
                100 if total_count > 0 else 0

            # List alternatives
            alts = []
            for v in variations:
                if v['tgt'] != primary['tgt']:
                    alts.append(f"{v['tgt']} ({v['count']})")

            writer.writerow([
                primary['src'],     # e.g., "Browser"
                msgctxt,            # e.g., "Visibility" or ""
                primary['tgt'],     # e.g., "ブラウザ"
                primary['count'],   # Count for THIS specific translation
                # Consistency relative to other variations
                f"{consistency:.1f}%",
                "; ".join(alts)     # e.g., "ブラウザー (5)"
            ])

    logger.info(f"  💾 [{langcode}] Wrote {len(final_map)} entries to {output_path}")


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

    # --- Partition records by langcode ---
    lang_groups = defaultdict(list)
    for i in range(len(docs)):
        langcode = str(metas[i].get('langcode', 'unknown')).strip()
        lang_groups[langcode].append((docs[i], metas[i]))

    # Apply --lang filter if provided
    if args.lang:
        if args.lang not in lang_groups:
            logger.error(f"❌ Language '{args.lang}' not found in database. "
                         f"Available: {sorted(lang_groups.keys())}")
            return
        lang_groups = {args.lang: lang_groups[args.lang]}

    logger.info(f"🌍 Found {len(lang_groups)} language(s): {sorted(lang_groups.keys())}")

    RAG_ANALYSIS_DIR = os.environ.get(
        "RAG_ANALYSIS_DIR", "/app/data/rag-analysis")
    logger.info(f"🔧 Config: RAG_ANALYSIS_DIR = {RAG_ANALYSIS_DIR}")

    os.makedirs(RAG_ANALYSIS_DIR, exist_ok=True)

    for langcode in sorted(lang_groups.keys()):
        extract_glossary_for_language(
            records=lang_groups[langcode],
            langcode=langcode,
            output_dir=RAG_ANALYSIS_DIR
        )

    # Summary log
    is_docker = os.path.exists('//.dockerenv')
    output_files = [f"db_derived_glossary_{lc}.csv" for lc in sorted(lang_groups.keys())]

    if is_docker:
        logger.info(
            "🎉 Done! Since you are running in Docker, files are available on your host at:")
        for fname in output_files:
            logger.info(f"   📄 ./data/rag-analysis/{fname}")
    else:
        logger.info(f"🎉 Done! Glossary files saved to '{RAG_ANALYSIS_DIR}':")
        for fname in output_files:
            logger.info(f"   📄 {fname}")


if __name__ == "__main__":
    main()
