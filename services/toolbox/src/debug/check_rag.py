'''
Diagnostic script to verify the health and content of the RAG (Retrieval-Augmented Generation) system.

What this script does:
1. Connects to the ChromaDB vector database service.
2. Checks the 'app_glossary' and 'app_tm' collections for data.
3. Peeks at the first record in each collection to verify data integrity.
4. Runs sample vector search queries ("View" and "Clear the cache") and prints detailed result metrics (distance, source, target).

How to run from host:
  docker compose exec toolbox python3 /app/src/debug/check_rag.py
'''

import chromadb
import sys

# Connect to the ChromaDB service
print("🔌 Connecting to ChromaDB...")
try:
    # We use the internal hostname 'chroma' as defined in docker-compose
    client = chromadb.HttpClient(host="chroma", port=8000)
    print("✅ Connected successfully.")
except Exception as e:
    print(f"❌ Connection failed: {e}")
    sys.exit(1)

# Function to test a collection


def test_collection(name, query_text):
    print(f"\n🔎 --- Testing Collection: {name} ---")
    try:
        col = client.get_collection(name)
        count = col.count()
        print(f"📊 Total Records: {count}")

        if count == 0:
            print("⚠️ Collection is empty. Did you run ingest.py?")
            return

        # 1. PEEK: Show first record
        print("👀 Peeking at first record...")
        peek = col.peek(limit=1)
        print(f"   Sample: {peek['documents'][0]}")

        # 2. QUERY: Run a vector search
        print(f"🕵️  Querying for '{query_text}'...")
        results = col.query(query_texts=[query_text], n_results=3)

        for i, doc in enumerate(results['documents'][0]):
            meta = results['metadatas'][0][i]
            dist = results['distances'][0][i]
            print(f"   Result {i+1} (Dist: {dist:.4f}):")
            print(f"     Src: {doc}")
            print(f"     Tgt: {meta.get('target', 'N/A')}")
            print(f"     Note: {meta.get('note', meta.get('context', ''))}")

    except Exception as e:
        print(f"❌ Error querying {name}: {e}")


# Run tests
test_collection("app_glossary", "View")
test_collection("app_tm", "Clear the cache")
