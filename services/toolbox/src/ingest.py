'''
Ingests the glossary and translation string into ChromaDB
with automated cleaning, deduplication, and incremental loading.
'''

import chromadb
from chromadb.utils import embedding_functions
import polib
import csv
import logging
import argparse
import hashlib
import os
from pathlib import Path
from typing import List, Dict, Generator, Any, Tuple, Set, Optional

# --- Configuration ---
# Allow overriding the source dir via environment variable
TM_SOURCE_DIR = Path(os.getenv("TM_SOURCE_DIR", "/app/tm_source"))
GLOSSARY_FILE = TM_SOURCE_DIR / "glossary.csv"
MODEL_NAME = "intfloat/multilingual-e5-large"
CHROMA_HOST = os.getenv("CHROMA_HOST", "chroma")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", 8000))

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# --- Helpers ---

def generate_content_hash(text: str) -> str:
    """Generates a deterministic MD5 hash for the given text to use as a Document ID."""
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def batch_generator(iterable, n=1) -> Generator[List[Any], None, None]:
    """Yields successive n-sized chunks from iterable."""
    l = len(iterable)
    for ndx in range(0, l, n):
        yield iterable[ndx:min(ndx + n, l)]

# --- Glossary Processor ---

def process_glossary(client: chromadb.HttpClient, ef: Any, source_path: Path, reset: bool = False) -> None:
    """
    Reads, cleans, deduplicates, and incrementally ingests glossary terms.
    If reset is True, deletes existing collection first.
    """
    COLLECTION_NAME = "drupal_glossary"
    logger.info(f"📚 Processing Glossary from {source_path}...")

    if not source_path.exists():
        logger.error(f"❌ Glossary file not found at: {source_path}")
        return

    if reset:
        try:
            client.delete_collection(COLLECTION_NAME)
            logger.info(f"   🗑️  Reset: Deleted existing '{COLLECTION_NAME}' collection.")
        except Exception:
            logger.info(f"   ℹ️  Reset: Collection '{COLLECTION_NAME}' did not exist.")

    try:
        gloss_col = client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"}
        )
    except Exception as e:
        logger.error(f"❌ Failed to get/create glossary collection: {e}")
        return

    unique_entries: Dict[str, str] = {} # Key: Clean Source, Value: Clean Target

    try:
        # Use 'utf-8-sig' to handle the BOM (\ufeff) marker automatically
        with source_path.open(mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                src = row.get('source', '').strip()
                tgt = row.get('target', '').strip()

                if src and tgt:
                    # Simple case-sensitive rule: First occurrence wins
                    if src not in unique_entries:
                        unique_entries[src] = tgt
    except Exception as e:
        logger.error(f"❌ Error reading glossary CSV: {e}")
        return

    logger.info(f"   🔹 Found {len(unique_entries)} unique glossary terms.")

    # Prepare Data
    ids = []
    documents = []
    metadatas = []

    for src, tgt in unique_entries.items():
        doc_text = "passage: " + src  # CRITICAL: Preserve Prefix
        doc_id = generate_content_hash(doc_text)
        
        ids.append(doc_id)
        documents.append(doc_text)
        metadatas.append({"target": tgt, "source_original": src})

    # Batch and Incremental Load
    _ingest_batches(gloss_col, ids, documents, metadatas, batch_size=200, label="Glossary")
    logger.info("✅ Glossary Ingestion Complete.")


# --- TM Processor ---

def process_tm(client: chromadb.HttpClient, ef: Any, source_dir: Path, reset: bool = False) -> None:
    """
    Recursively finds PO files, deduplicates by msgid, and incrementally ingests.
    If reset is True, deletes existing collection first.
    """
    COLLECTION_NAME = "drupal_tm"
    logger.info(f"💾 Processing Translation Memory from {source_dir}...")

    if not source_dir.exists():
        logger.error(f"❌ Source directory not found: {source_dir}")
        return

    if reset:
        try:
            client.delete_collection(COLLECTION_NAME)
            logger.info(f"   🗑️  Reset: Deleted existing '{COLLECTION_NAME}' collection.")
        except Exception:
            logger.info(f"   ℹ️  Reset: Collection '{COLLECTION_NAME}' did not exist.")

    try:
        tm_col = client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"}
        )
    except Exception as e:
        logger.error(f"❌ Failed to get/create TM collection: {e}")
        return

    # ROBUST FILE FINDING
    # Use rglob for recursive finding and check both lowercase and uppercase extensions
    po_files = list(source_dir.rglob("*.po")) + list(source_dir.rglob("*.PO"))
    po_files = list(set(po_files)) # Remove duplicates if any

    if not po_files:
        logger.warning(f"⚠️  Found 0 reference .po files in {source_dir}")
        logger.warning("   🔎 Debugging Directory Contents:")
        try:
            # List top-level files to help user debug volume mounts
            for item in source_dir.iterdir():
                logger.info(f"      - {item.name}")
        except Exception as e:
            logger.error(f"      (Could not list directory: {e})")
        return
    else:
        logger.info(f"   🔍 Found {len(po_files)} reference .po files.")

    unique_tm: Dict[str, Tuple[str, str]] = {} # Key: msgid, Value: (msgstr, filename)
    logger.info("   ⏳ Reading and deduplicating PO entries...")

    for po_file in po_files:
        try:
            po = polib.pofile(str(po_file))
            base_filename = po_file.name

            for entry in po:
                if entry.msgid and entry.msgstr and "fuzzy" not in entry.flags:
                    clean_src = entry.msgid.strip()
                    clean_tgt = entry.msgstr.strip()

                    if clean_src and clean_tgt:
                        if clean_src not in unique_tm:
                            unique_tm[clean_src] = (clean_tgt, base_filename)
        except Exception as e:
            logger.warning(f"   ⚠️ Error reading file {po_file}: {e}")

    logger.info(f"   🔹 Found {len(unique_tm)} unique TM entries after deduplication.")

    # Prepare Data
    ids = []
    documents = []
    metadatas = []

    for src, (tgt, fname) in unique_tm.items():
        doc_text = "passage: " + src # CRITICAL: Preserve Prefix
        doc_id = generate_content_hash(doc_text)

        ids.append(doc_id)
        documents.append(doc_text)
        metadatas.append({"target": tgt, "file": fname})

    # Batch and Incremental Load
    _ingest_batches(tm_col, ids, documents, metadatas, batch_size=400, label="TM")
    logger.info("✅ TM Ingestion Complete.")


def _ingest_batches(collection: Any, ids: List[str], documents: List[str], metadatas: List[Dict], batch_size: int, label: str) -> None:
    """
    Helper to handle batching and incremental loading (skipping existing IDs).
    """
    total_new = 0
    total_skipped = 0
    
    logger.info(f"   🚀 Starting vector ingestion for {label}...")

    for ch_ids, ch_docs, ch_meta in zip(
      batch_generator(ids, batch_size),
      batch_generator(documents, batch_size),
      batch_generator(metadatas, batch_size)
    ):
        
        # Incremental Check: Check which IDs already exist
        try:
            existing_records = collection.get(ids = ch_ids, include = [])
            existing_ids = set(existing_records['ids'])
        except Exception as e:
            logger.warning(f"Failed to check existence for batch, attempting upsert all. Error: {e}")
            existing_ids = set()

        # Filter for NEW items only
        new_ids = []
        new_docs = []
        new_meta = []

        for i, doc_id in enumerate(ch_ids):
            if doc_id not in existing_ids:
                new_ids.append(doc_id)
                new_docs.append(ch_docs[i])
                new_meta.append(ch_meta[i])
            else:
                total_skipped += 1

        # Upsert ONLY new
        if new_ids:
            try:
                collection.add(ids=new_ids, documents=new_docs, metadatas=new_meta)
                total_new += len(new_ids)
            except Exception as e:
                logger.error(f"❌ Error adding batch to {label}: {e}")

        if (total_new + total_skipped) % 2000 == 0:
            logger.info(f"      ... Processed {total_new + total_skipped} items ({total_new} new, {total_skipped} skipped)")

    logger.info(f"   🏁 {label} Summary: {total_new} inserted, {total_skipped} skipped (deduplicated).")


# --- Main Orchestration ---

def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest translation data into ChromaDB.")
    parser.add_argument("--glossary-only", action="store_true", help="Only ingest the glossary CSV.")
    parser.add_argument("--tm-only", action="store_true", help="Only ingest the .po files.")
    parser.add_argument("--reset", action="store_true", help="Delete existing collections before ingestion (Cleanup dupes).")
    args = parser.parse_args()

    run_glossary = True
    run_tm = True

    if args.glossary_only:
        run_tm = False
    if args.tm_only:
        run_glossary = False
    if args.glossary_only and args.tm_only:
        logger.warning("⚠️  Both flags set. Running BOTH.")
        run_glossary = True
        run_tm = True

    logger.info("🔌 Connecting to ChromaDB...")
    try:
        client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    except Exception as e:
        logger.critical(f"❌ Failed to connect to ChromaDB at {CHROMA_HOST}:{CHROMA_PORT}. Error: {e}")
        return

    logger.info(f"⏳ Loading Embedding Model ({MODEL_NAME})...")
    try:
        e5_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=MODEL_NAME
        )
    except Exception as e:
        logger.critical(f"❌ Failed to load embedding model: {e}")
        return

    if run_glossary:
        process_glossary(client, e5_ef, GLOSSARY_FILE, reset=args.reset)
    
    if run_tm:
        process_tm(client, e5_ef, TM_SOURCE_DIR, reset=args.reset)

    logger.info("🎉 Ingestion Pipeline Finished.")

if __name__ == "__main__":
    main()
