import os
import csv
import re
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
    # 1. Check Japanese Target (simple substring)
    if term_tgt not in record_tgt:
        return False

    # 2. Check English Source (Word Boundary is critical)
    pattern = r'\b' + re.escape(term_src) + r'\b'
    if re.search(pattern, record_src, re.IGNORECASE):
        return True

    return False



def main() -> None:
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

    logger.info(
        f"✅ Retrieved {len(docs)} records. Phase 1: Identifying Variations...")

    # --- PHASE 1: Identify Candidates (All Variations) ---
    # candidates[src_lower] = set of (original_src, target_string)
    candidates = defaultdict(set)

    for i in range(len(docs)):
        src = docs[i].strip()
        tgt = str(metas[i].get('target', '')).strip()

        if not src or not tgt:
            continue

        # Only consider short terms (1-3 words) as glossary headers
        word_count = len(src.split())
        if 0 < word_count <= 3 and len(src) < 50:
            src_lower = src.lower()
            # Store every variation found, e.g. ('Browser', 'ブラウザ') AND ('Browser', 'ブラウザー')
            candidates[src_lower].add((src, tgt))

    logger.info(
        f"🔍 Found {len(candidates)} unique English terms. Phase 2: Counting Frequencies...")

    # --- PHASE 2: Global Frequency Scan ---
    # We count how often EACH variation appears in the full database

    # Optimization: Pre-load records
    records = []
    for i in range(len(docs)):
        d_src = docs[i].strip()
        d_tgt = str(metas[i].get('target', '')).strip()
        records.append((d_src, d_tgt))

    # tallied_terms = list of dicts with counts
    tallied_terms = []

    for src_key, variations in candidates.items():
        for (head_src, head_tgt) in variations:
            count = 0
            for r_src, r_tgt in records:
                if is_substring_match(head_src, head_tgt, r_src, r_tgt):
                    count += 1

            # Keep if it appears more than once
            if count > 1:
                tallied_terms.append({
                    'key': src_key,
                    'src': head_src,
                    'tgt': head_tgt,
                    'count': count
                })

    logger.info(f"📉 Phase 3: Pruning Superstrings...")

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

            # Check if English 'Action' is in 'Action ID'
            if is_substring_match(short['src'], short['tgt'], long['src'], long['tgt']):
                # If 'Action' -> 'アクション' covers 'Action ID' -> 'アクションID'
                # We suppress 'Action ID'
                ignore_indices.add(j)

    # --- PHASE 4: Aggregation by English Term ---
    # Group surviving terms by their English key
    for i, item in enumerate(tallied_terms):
        if i not in ignore_indices:
            final_map[item['key']].append(item)

    RAG_ANALYSIS_DIR = os.environ.get(
        "RAG_ANALYSIS_DIR", "/app/data/rag-analysis")
    output_path = os.path.join(RAG_ANALYSIS_DIR, "db_derived_glossary.csv")
    logger.info(f"🔧 Config: RAG_ANALYSIS_DIR = {RAG_ANALYSIS_DIR}")
    logger.info(f"💾 Exporting glossary...")

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(
            ['Source', 'Target', 'Total Occurrences', 'Consistency', 'Alternatives'])

        # Sort alphabetically by Source
        sorted_keys = sorted(final_map.keys())

        for key in sorted_keys:
            variations = final_map[key]

            # Calculate total occurrences for this English term (sum of all variations)
            # Note: This sum might double-count if "ブラウザ" is inside "ブラウザー".
            # But for a glossary, showing the "Winner" is the priority.

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
                primary['tgt'],     # e.g., "ブラウザ"
                primary['count'],   # Count for THIS specific translation
                # Consistency relative to other variations
                f"{consistency:.1f}%",
                "; ".join(alts)     # e.g., "ブラウザー (5)"
            ])

    # Logic to replace the final logger.info calls:
    is_docker = os.path.exists('/.dockerenv')

    if is_docker:
        logger.info(
            "🎉 Done! Since you are running in Docker, the file is available on your host at:")
        logger.info("   📄 ./data/rag-analysis/db_derived_glossary.csv")
    else:
        logger.info(f"🎉 Done! Glossary saved to '{output_path}'.")

if __name__ == "__main__":
    main()
