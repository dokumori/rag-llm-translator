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
from core.config import Config
from core.utils import find_po_files
from infrastructure import get_chroma_client, get_embedding_function

# --- Configuration ---
# Allow overriding the source dir via environment variable
TM_SOURCE_DIR = Path(Config.TM_SOURCE_DIR)
GLOSSARY_FILE = TM_SOURCE_DIR / "glossary.csv"
MODEL_NAME = Config.EMBEDDING_MODEL_NAME
CHROMA_HOST = Config.CHROMA_HOST
CHROMA_PORT = Config.CHROMA_PORT

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


def pre_flight_check(run_glossary: bool, run_tm: bool) -> bool:
    """
    Validates input files before performing expensive operations.
    Returns True if checks pass, False otherwise.
    """
    logger.info("🔍 Running Pre-flight Checks...")

    if not TM_SOURCE_DIR.exists():
        logger.error(f"❌ Source directory not found: {TM_SOURCE_DIR}")
        return False

    if run_glossary:
        csv_files = list(TM_SOURCE_DIR.glob("*.csv"))
        if len(csv_files) > 1:
            file_list = ", ".join([f.name for f in csv_files])
            logger.error(f"❌ Multiple glossary files detected: [{file_list}]")
            logger.error(
                "👉 Please provide only ONE CSV file or combine them into one.")
            return False
        elif len(csv_files) == 1:
            logger.info(
                f"   ✅ Single glossary file found: {csv_files[0].name}")
        else:
             logger.info("   ℹ️  No glossary CSV found (Glossary step will skip gracefully).")

    logger.info("✅ Pre-flight Checks Passed.")
    return True

# --- Glossary Processor ---


def process_glossary(client: chromadb.HttpClient, ef: Any, source_path: Path, reset: bool = False) -> None:
    """
    Reads, cleans, deduplicates, and incrementally ingests glossary terms.
    If reset is True, deletes existing collection first.
    """
    COLLECTION_NAME = Config.GLOSSARY_COLLECTION

    # Scans the parent directory of the provided path for any single glossary CSV file.
    scan_dir = source_path.parent
    
    logger.info(f"📚 Scanning for glossary CSVs in {scan_dir}...")
    
    csv_files = list(scan_dir.glob("*.csv"))

    if not csv_files:
        logger.info("ℹ️ No glossary CSV found. Skipping glossary ingestion.")
        return

    # Check for > 1 is handled by pre_flight_check(), so we safe to pick [0]
    target_file = csv_files[0]
    logger.info(f"📚 Processing single glossary: {target_file.name}")

    if not target_file.exists():
         # Should not happen given glob, but just in case
        logger.error(f"❌ Glossary file not found at: {target_file}")
        return

    if reset:
        try:
            client.delete_collection(COLLECTION_NAME)
            logger.info(
                f"   🗑️  Reset: Deleted existing '{COLLECTION_NAME}' collection.")
        except Exception:
            logger.info(
                f"   ℹ️  Reset: Collection '{COLLECTION_NAME}' did not exist.")

    try:
        gloss_col = client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"}
        )
    except Exception as e:
        logger.error(f"❌ Failed to get/create glossary collection: {e}")
        return

    # Key: Clean Source, Value: Clean Target
    unique_entries: Dict[str, str] = {}

    try:
        # Use 'utf-8-sig' to handle the BOM (\ufeff) marker automatically
        with target_file.open(mode='r', encoding='utf-8-sig') as f:
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
        # Unique ID by content to allow idempotent loading to prevent duplicate
        # entries in the DB
        doc_id = generate_content_hash(doc_text)

        ids.append(doc_id)
        documents.append(doc_text)
        metadatas.append({"target": tgt, "source_original": src})

    # Batch and Incremental Load
    _ingest_batches(gloss_col, ids, documents, metadatas,
                    batch_size=200, label="Glossary")
    logger.info("✅ Glossary Ingestion Complete.")


# --- TM Processor ---

def process_tm(client: chromadb.HttpClient, ef: Any, source_dir: Path, reset: bool = False) -> None:
    """
    Recursively finds PO files, deduplicates by msgid, and incrementally ingests.
    If reset is True, deletes existing collection first.
    """
    COLLECTION_NAME = Config.TM_COLLECTION
    logger.info(f"💾 Processing Translation Memory from {source_dir}...")

    if not source_dir.exists():
        logger.error(f"❌ Source directory not found: {source_dir}")
        return

    if reset:
        try:
            client.delete_collection(COLLECTION_NAME)
            logger.info(
                f"   🗑️  Reset: Deleted existing '{COLLECTION_NAME}' collection.")
        except Exception:
            logger.info(
                f"   ℹ️  Reset: Collection '{COLLECTION_NAME}' did not exist.")

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
    # Use shared utility to find all .po variations recursively
    po_files = [Path(p) for p in find_po_files(str(source_dir), recursive=True)]

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

    # Key: msgid, Value: (msgstr, filename)
    unique_tm: Dict[str, Tuple[str, str]] = {}
    logger.info("   ⏳ Reading and deduplicating PO entries...")

    for po_file in po_files:
        try:
            po = polib.pofile(str(po_file))
            base_filename = po_file.name

            for entry in po:
                if entry.msgid and entry.msgstr and "fuzzy" not in entry.flags:
                    clean_src = entry.msgid.strip()
                    clean_tgt = entry.msgstr.strip()

                    # check to ensure neither is empty
                    if clean_src and clean_tgt:
                        
                        # Deduplication logic: if the same msgid is found in multiple files, 
                        # the last one will overwrite the previous ones
                        if clean_src not in unique_tm:
                            unique_tm[clean_src] = (clean_tgt, base_filename)
        except Exception as e:
            logger.warning(f"   ⚠️ Error reading file {po_file}: {e}")

    logger.info(
        f"   🔹 Found {len(unique_tm)} unique TM entries after deduplication.")

    # Prepare Data
    ids = []
    documents = []
    metadatas = []

    for src, (tgt, fname) in unique_tm.items():
        doc_text = "passage: " + src  # CRITICAL: Preserve Prefix
        # Unique ID by content, allows idempotent (incremental) loading
        doc_id = generate_content_hash(doc_text)

        ids.append(doc_id)
        documents.append(doc_text)
        metadatas.append({"target": tgt, "file": fname})

    # Batch and Incremental Load
    _ingest_batches(tm_col, ids, documents, metadatas,
                    batch_size=400, label="TM")
    logger.info("✅ TM Ingestion Complete.")


def _ingest_batches(collection: Any, ids: List[str], documents: List[str], metadatas: List[Dict], batch_size: int, label: str) -> None:
    """
    Helper to handle batching and incremental loading (skipping existing IDs).
    """
    total_new = 0
    total_skipped = 0

    logger.info(f"   🚀 Starting vector ingestion for {label}...")

    # Process IDs, documents, and metadatas in synchronized chunks (ch_*)
    for ch_ids, ch_docs, ch_meta in zip(
        batch_generator(ids, batch_size),
        batch_generator(documents, batch_size),
        batch_generator(metadatas, batch_size)
    ):

        # Incremental Check: Check which IDs already exist
        try:
            existing_records = collection.get(ids=ch_ids, include=[])
            existing_ids = set(existing_records['ids'])
        except Exception as e:
            logger.warning(
                f"Failed to check existence for batch, attempting upsert all. Error: {e}")
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
                collection.add(ids=new_ids, documents=new_docs,
                               metadatas=new_meta)
                total_new += len(new_ids)
            except Exception as e:
                logger.error(
                    f"❌ Error adding batch to {label}: {e}", exc_info=True)
                # Fail fast on write errors to avoid partial/corrupted state
                raise e

        if (total_new + total_skipped) % 2000 == 0:
            logger.info(
                f"      ... Processed {total_new + total_skipped} items ({total_new} new, {total_skipped} skipped)")

    logger.info(
        f"   🏁 {label} Summary: {total_new} inserted, {total_skipped} skipped (deduplicated).")


# --- Main Orchestration ---

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest translation data into ChromaDB.")
    parser.add_argument("--glossary-only", action="store_true",
                        help="Only ingest the glossary CSV.")
    parser.add_argument("--tm-only", action="store_true",
                        help="Only ingest the .po files.")
    parser.add_argument("--reset", action="store_true",
                        help="Delete existing collections before ingestion (Cleanup dupes).")
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

    # --- Pre-Flight Check ---
    if not pre_flight_check(run_glossary, run_tm):
        logger.error("🛑 Pre-flight checks failed. Exiting.")
        return

    logger.info(f"🔌 Connecting to ChromaDB at {CHROMA_HOST}:{CHROMA_PORT}...")
    try:
        client = get_chroma_client()
    except Exception as e:
        logger.critical(
             f"❌ Failed to connect to ChromaDB at {CHROMA_HOST}:{CHROMA_PORT}. Error: {e}")
        return

    logger.info(f"⏳ Loading Embedding Model ({MODEL_NAME})...")
    try:
        e5_ef = get_embedding_function()
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
