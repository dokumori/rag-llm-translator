'''
Checks if the `query:` / `passage:` prefixes are added
'''
import chromadb
import os
import sys

def check_db():
  # Connect to the Chroma instance using environment variables
  host = os.environ.get("CHROMA_HOST", "chroma")
  port = int(os.environ.get("CHROMA_PORT", 8000))

  print(f"🔌 Connecting to ChromaDB at {host}:{port}...")
  try:
    client = chromadb.HttpClient(host = host, port = port)
  except Exception as e:
    print(f"❌ Error connecting to ChromaDB: {e}")
    sys.exit(1)

  collections = ["drupal_glossary", "drupal_tm"]

  for col_name in collections:
    print(f"\n🔍 Checking Collection: {col_name}")
    print("-" * 40)
    try:
      col = client.get_collection(col_name)
      
      # 1. Check Distance Metric (Metadata)
      space = col.metadata.get("hnsw:space", "l2 (default)")
      if space == "cosine":
        print(f"✅ Metric: {space}")
      else:
        print(f"❌ Metric: {space} (Expected: cosine)")

      # 2. Check for Prefixes in Documents
      res = col.get(limit = 3, include = ["documents"])
      if not res["documents"]:
        print("⚠️  No documents found in this collection.")
        continue

      for i, doc in enumerate(res["documents"]):
        if doc.startswith("passage: "):
          status = "✅ PREFIX FOUND"
        else:
          status = "❌ NO PREFIX"
        print(f" [{i}] {status} | Content: {doc[:60]}...")

    except Exception as e:
      print(f" ❌ Error accessing {col_name}: {e}")

if __name__ == "__main__":
  check_db()
