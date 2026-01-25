'''
Checks if the `query:` / `passage:` prefixes are added
'''
import chromadb
import os
import sys
from infrastructure import get_chroma_client


def check_db():
    # Connect to the Chroma instance using environment variables
    print(f"🔌 Connecting to ChromaDB...")
    try:
        client = get_chroma_client()
    except Exception as e:
        print(f"❌ Error connecting to ChromaDB: {e}")
        sys.exit(1)

    collections = ["app_glossary", "app_tm"]

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
            res = col.get(limit=3, include=["documents"])
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
