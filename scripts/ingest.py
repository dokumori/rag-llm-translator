import chromadb
import pandas as pd
import polib
import os
import sys
import glob

# Configuration
# The volume is mounted to /app/tm_source in docker-compose
TM_SOURCE_DIR = "/app/tm_source"
GLOSSARY_FILE = os.path.join(TM_SOURCE_DIR, "glossary.csv")

# Connect to DB
print("🔌 Connecting to ChromaDB...")
try:
    # We use the service name "chroma" from docker-compose
    client = chromadb.HttpClient(
        host=os.environ.get("CHROMA_HOST", "chroma"), port=int(os.environ.get("CHROMA_PORT", 8000))
    )
except Exception as e:
    print(f"❌ Error connecting to ChromaDB: {e}")
    sys.exit(1)

# Reset Collections (Clean Slate)
try:
    client.delete_collection("drupal_glossary")
    client.delete_collection("drupal_tm")
except:
    pass

glossary_collection = client.create_collection(name="drupal_glossary")
tm_collection = client.create_collection(name="drupal_tm")

# ---------------------------------------------------------
# Part A: Ingest Glossary
# ---------------------------------------------------------
if os.path.exists(GLOSSARY_FILE):
    try:
        df = pd.read_csv(GLOSSARY_FILE, encoding='utf-8-sig', dtype=str)
        df.columns = df.columns.str.strip().str.lower()

        if 'source' in df.columns:
            if 'note' not in df.columns: df['note'] = ""
            df.fillna("", inplace=True)

            glossary_collection.add(
                ids=[f"gloss_{i}" for i in range(len(df))],
                documents=df['source'].tolist(),
                metadatas=df[['target', 'note']].to_dict('records')
            )
            print(f"✅ Ingested {len(df)} glossary terms.")
        else:
            print(f"⚠️ 'source' column missing in {GLOSSARY_FILE}")
    except Exception as e:
        print(f"⚠️ Error reading glossary: {e}")
else:
    print(f"⚠️ No glossary.csv found in {TM_SOURCE_DIR}")

# ---------------------------------------------------------
# Part B: Ingest Reference PO Files
# ---------------------------------------------------------
po_files = glob.glob(os.path.join(TM_SOURCE_DIR, "**/*.po"), recursive=True)
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
            tm_collection.add(ids=ids, documents=docs, metadatas=meta)

        tm_count += len(valid_entries)
    except Exception as e:
        print(f"⚠️ Failed to process {po_file}: {e}")

print(f"🎉 RAG Ingestion Complete! {tm_count} sentences ready.")
