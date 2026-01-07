import chromadb
from chromadb.utils import embedding_functions
import pandas as pd
import polib
import os
import sys
import glob
import argparse

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
  # If both are True (user error), we default to running the one explicitly asked for,
  # but if flags conflict, usually the last one 'wins' or we stick to logic.
  # If user typed: python ingest.py --glossary-only --tm-only
  # run_tm becomes False, then run_glossary becomes False. Nothing runs.
  # Let's fix that edge case:
  if args.glossary_only and args.tm_only:
    print("⚠️  Both flags set. Running BOTH.")
    run_glossary = True
    run_tm = True


# Connect to DB
print("🔌 Connecting to ChromaDB...")
try:
  client = chromadb.HttpClient(
    host = os.environ.get("CHROMA_HOST", "chroma"),
    port = int(os.environ.get("CHROMA_PORT", 8000))
  )
except Exception as e:
  print(f"❌ Error connecting to ChromaDB: {e}")
  sys.exit(1)

# --- Define the E5 Embedding Function ---
e5_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
  model_name = "intfloat/multilingual-e5-large"
)

# Reset Collections based on what we are running
# Note: We only delete the collection we are about to re-ingest to preserve the other.
try:
  if run_glossary:
    try:
      client.delete_collection("drupal_glossary")
    except:
      pass # Collection didn't exist
    
    # Re-create immediately
    glossary_collection = client.create_collection(
      name = "drupal_glossary",
      embedding_function = e5_ef
    )

  if run_tm:
    try:
      client.delete_collection("drupal_tm")
    except:
      pass
      
    tm_collection = client.create_collection(
      name = "drupal_tm",
      embedding_function = e5_ef
    )
except Exception as e:
  print(f"⚠️ Error resetting collections: {e}")

# ---------------------------------------------------------
# Part A: Ingest Glossary
# ---------------------------------------------------------
if run_glossary:
  if os.path.exists(GLOSSARY_FILE):
    try:
      df = pd.read_csv(GLOSSARY_FILE, encoding = 'utf-8-sig', dtype = str)
      df.columns = df.columns.str.strip().str.lower()

      if 'source' in df.columns:
        # Ensure new columns exist, fill with empty string if missing
        if 'note' not in df.columns: df['note'] = ""
        if 'category' not in df.columns: df['category'] = ""
        if 'target' not in df.columns: df['target'] = ""
        
        df.fillna("", inplace = True)

        # We now store 'category' and 'note' in metadata
        glossary_collection.add(
          ids = [f"gloss_{i}" for i in range(len(df))],
          documents = df['source'].tolist(),
          metadatas = df[['target', 'category', 'note']].to_dict('records')
        )
        print(f"✅ Ingested {len(df)} glossary terms (with Category/Note).")
      else:
        print(f"⚠️ 'source' column missing in {GLOSSARY_FILE}")
    except Exception as e:
      print(f"⚠️ Error reading glossary: {e}")
  else:
    print(f"⚠️ No glossary.csv found in {TM_SOURCE_DIR}")
else:
  print("⏩ Skipping Glossary Ingestion.")

# ---------------------------------------------------------
# Part B: Ingest Reference PO Files
# ---------------------------------------------------------
if run_tm:
  po_files = glob.glob(os.path.join(TM_SOURCE_DIR, "**/*.po"), recursive = True)
  print(f"🔍 Found {len(po_files)} reference .po files.")

  def chunks(lst, n):
    for i in range(0, len(lst), n):
      yield lst[i:i + n]

  tm_count = 0
  for po_file in po_files:
    try:
      po = polib.pofile(po_file)
      valid_entries = [e for e in po if e.msgid and e.msgstr and "fuzzy" not in e.flags]

      if not valid_entries: continue

      BATCH_SIZE = 500
      current_ids = [f"tm_{os.path.basename(po_file)}_{i}" for i in range(len(valid_entries))]
      current_docs = [e.msgid for e in valid_entries]
      current_meta = [{"target": e.msgstr, "file": os.path.basename(po_file)} for e in valid_entries]

      print(f"📄 Processing {os.path.basename(po_file)} ({len(valid_entries)} items)...")

      for i, (ids, docs, meta) in enumerate(
        zip(
          chunks(current_ids, BATCH_SIZE),
          chunks(current_docs, BATCH_SIZE),
          chunks(current_meta, BATCH_SIZE)
          )
        ):
        tm_collection.add(ids = ids, documents = docs, metadatas = meta)

      tm_count += len(valid_entries)
    except Exception as e:
      print(f"⚠️ Failed to process {po_file}: {e}")

  print(f"🎉 RAG Ingestion Complete! {tm_count} sentences ready.")
else:
  print("⏩ Skipping PO File Ingestion.")
