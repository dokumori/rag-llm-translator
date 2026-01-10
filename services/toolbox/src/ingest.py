'''
Ingests the glossary and translation string into ChromaDB
with automated cleaning and deduplication.
'''

import chromadb
from chromadb.utils import embedding_functions
import polib
import os
import sys
import glob
import argparse
import csv

# Configuration
TM_SOURCE_DIR = "/app/tm_source"
GLOSSARY_FILE = os.path.join(TM_SOURCE_DIR, "glossary.csv")

# --- 0. Parse Arguments ---
parser = argparse.ArgumentParser(description = "Ingest translation data into ChromaDB.")
parser.add_argument("--glossary-only", action = "store_true", help = "Only ingest the glossary CSV.")
parser.add_argument("--tm-only", action = "store_true", help = "Only ingest the .po files.")
args = parser.parse_args()

# Logic to decide what to run
run_glossary = True
run_tm = True

if args.glossary_only:
  run_tm = False
if args.tm_only:
  run_glossary = False
if args.glossary_only and args.tm_only:
  print("⚠️  Both flags set. Running BOTH.")
  run_glossary = True
  run_tm = True

# Connect to DB
print("🔌 Connecting to ChromaDB...")
client = chromadb.HttpClient(host='chroma', port=8000)

# Load Embedding Model
print("⏳ Loading Embedding Model (intfloat/multilingual-e5-large)...")
e5_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="intfloat/multilingual-e5-large"
)

# ---------------------------------------------------------
# Part A: Ingest Glossary (CSV)
# ---------------------------------------------------------
if run_glossary:
  print("\n📚 Processing Glossary...")
  try:
    # 1. Reset Collection
    try:
      client.delete_collection("drupal_glossary")
      print("   🗑️  Deleted existing 'drupal_glossary' collection.")
    except Exception:
      pass
    
    gloss_col = client.create_collection(
      name="drupal_glossary", 
      embedding_function=e5_ef,
      metadata={"hnsw:space": "cosine"}
    )

    # 2. Read and Clean CSV
    unique_entries = {} # Key: Lowercase Source, Value: (Original Source, Target)
    
    if os.path.exists(GLOSSARY_FILE):
      # Use 'utf-8-sig' to handle the BOM (\ufeff) marker automatically
      with open(GLOSSARY_FILE, mode='r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
          # Clean Whitespace
          src = row.get('source', '').strip()
          tgt = row.get('target', '').strip()
          
          if not src or not tgt:
            continue
            
          # DEDUPLICATION (Simple Case-Sensitive)
          key = src 
          if key not in unique_entries:
            unique_entries[key] = tgt

      # 3. Batch Ingest
      batch_ids = []
      batch_docs = []
      batch_meta = []
      BATCH_SIZE = 200
      
      print(f"   🔹 Found {len(unique_entries)} unique glossary terms.")

      for i, (src, tgt) in enumerate(unique_entries.items()):
        # CRITICAL: Add Prefix
        doc_text = "passage: " + src
        
        batch_ids.append(f"gloss_{i}")
        batch_docs.append(doc_text)
        batch_meta.append({"target": tgt, "source_original": src})
        
        if len(batch_ids) >= BATCH_SIZE:
          gloss_col.add(ids=batch_ids, documents=batch_docs, metadatas=batch_meta)
          batch_ids = []
          batch_docs = []
          batch_meta = []
          # Only print occasionally to reduce log noise
          if (i + 1) % 1000 == 0:
            print(f"   ... Ingested {i+1} glossary terms")

      # Final batch
      if batch_ids:
        gloss_col.add(ids=batch_ids, documents=batch_docs, metadatas=batch_meta)
      
      print("✅ Glossary Ingestion Complete.")
      
    else:
      print(f"❌ Glossary file not found at: {GLOSSARY_FILE}")

  except Exception as e:
    print(f"❌ Error ingesting glossary: {e}")

# ---------------------------------------------------------
# Part B: Ingest Reference PO Files (Translation Memory)
# ---------------------------------------------------------

if run_tm:
  print("\n💾 Processing Translation Memory (.po files)...")
  try:
    # 1. Reset Collection
    try:
      client.delete_collection("drupal_tm")
      print("   🗑️  Deleted existing 'drupal_tm' collection.")
    except Exception:
      pass

    tm_col = client.create_collection(
      name="drupal_tm", 
      embedding_function=e5_ef,
      metadata={"hnsw:space": "cosine"}
    )

    po_files = glob.glob(os.path.join(TM_SOURCE_DIR, "**/*.po"), recursive = True)
    print(f"   🔍 Found {len(po_files)} reference .po files.")

    # 2. Extract and Deduplicate TM Entries
    # Because 'Save' might appear in 50 different files, we deduplicate by msgid
    # to keep the vector space clean.
    unique_tm = {} # Key: msgid, Value: (msgstr, filename)

    print("   ⏳ Reading and deduplicating PO entries (this may take a moment)...")
    for po_file in po_files:
      try:
        po = polib.pofile(po_file)
        base_filename = os.path.basename(po_file)
        
        # Valid entry: has ID, Translation, and NOT fuzzy
        for entry in po:
            if entry.msgid and entry.msgstr and "fuzzy" not in entry.flags:
                clean_src = entry.msgid.strip()
                clean_tgt = entry.msgstr.strip()
                
                # If we haven't seen this source sentence yet, store it
                # (You could add logic here to prefer 'longer' translations or specific files)
                if clean_src and clean_tgt and clean_src not in unique_tm:
                    unique_tm[clean_src] = (clean_tgt, base_filename)

      except Exception as e:
        print(f"   ⚠️ Error reading file {po_file}: {e}")
    
    print(f"   🔹 Found {len(unique_tm)} unique TM entries after deduplication.")

    # 3. Batch Ingest
    def chunks(lst, n):
      for i in range(0, len(lst), n):
        yield lst[i:i + n]

    # Convert dict to lists for batching
    tm_ids = []
    tm_docs = []
    tm_meta = []
    
    for i, (src, (tgt, fname)) in enumerate(unique_tm.items()):
        tm_ids.append(f"tm_{i}")
        tm_docs.append("passage: " + src) # CRITICAL: Add Prefix
        tm_meta.append({"target": tgt, "file": fname})

    BATCH_SIZE = 400
    total_count = 0

    print(f"   🚀 Starting vector ingestion...")
    for ch_ids, ch_docs, ch_meta in zip(chunks(tm_ids, BATCH_SIZE), 
                                        chunks(tm_docs, BATCH_SIZE), 
                                        chunks(tm_meta, BATCH_SIZE)):
        tm_col.add(ids=ch_ids, documents=ch_docs, metadatas=ch_meta)
        total_count += len(ch_ids)
        if total_count % 2000 == 0:
            print(f"      ... Processed {total_count} entries")

    print(f"✅ TM Ingestion Complete. Total items: {total_count}")

  except Exception as e:
    print(f"❌ Error ingesting TM: {e}")

print("\n🎉 Ingestion Pipeline Finished.")
