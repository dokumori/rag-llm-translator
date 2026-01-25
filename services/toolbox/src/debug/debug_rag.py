'''
Diagnostic script to recursively query the RAG system with a specific batch of test sentences.

What this script does:
1. Connects to the ChromaDB service.
2. Defines a hardcoded list of test sentences (batch_content).
3. Iterates through 'app_glossary' and 'app_tm' collections.
4. Queries ChromaDB for specific indices in the batch (0, 4, 10).
5. Prints the closest matches, their distances, and metadata (source/target).

How to run from host:
  docker compose exec toolbox python3 /app/src/debug/debug_rag.py
'''
import chromadb

import os
import json


def main():
    # 1. Setup Client
    print("--- Connecting to ChromaDB ---")
    chroma_host = os.environ.get("CHROMA_HOST", "chroma")
    chroma_port = int(os.environ.get("CHROMA_PORT", 8000))

    try:
        client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
        print(f"Connected to {chroma_host}:{chroma_port}")
    except Exception as e:
        print(f"Connection failed: {e}")
        return

    # 2. Define the exact batch content you want to test
    batch_content = [
        "Allows a user to configure pathauto settings, configure patterns for automated aliases, bulk update and delete URL-aliases.",
        "Allows a user to bulk delete aliases.",
        "Allows a user to bulk update aliases.",
        "This allows users without the Administer redirect settings to ignore specific 404 requests, without the ability to customize the 404 exclude patterns.",
        "Configure scheduler - set default times, lightweight cron.",
        "Allows users to set a start and end time for %singular_label publication.",
        "Allows users to see a list of all %plural_label that are scheduled.",
        "Users with this permission will be able to administer the Simple Add More module settings.",
        "To delete a revision you also need permission to delete the taxonomy term.",
        "To revert a revision you also need permission to edit the taxonomy term.",
        "Allows a user to configure which entity types can use the trash bin.",
        "Users with this permission will be able to permanently delete (purge) trashed entities from the system.",
        "Users with this permission will be able to restore entities from the trash bin.",
        "Allows a user to view deleted entities.",
        "Allows a user to see the contents of the trash bin."
    ]

    # 3. Query Collections
    collections_to_test = ["app_glossary", "app_tm"]

    for col_name in collections_to_test:
        print(f"\n{'='*20} Testing Collection: {col_name} {'='*20}")

        try:
            collection = client.get_collection(col_name)
            count = collection.count()
            print(f"Collection '{col_name}' contains {count} documents.")
        except Exception as e:
            print(f"Could not access collection '{col_name}': {e}")
            continue

        # Query just the first 3 items to avoid flooding the console,
        # or loop through all if you need deep verification.
        # Here we pick 3 diverse examples from your list.
        test_indices = [0, 4, 10]  # Pathauto, Scheduler, Trash bin

        for i in test_indices:
            query_text = batch_content[i]
            print(f"\n🔎 Querying for: '{query_text[:60]}...'")

            results = collection.query(
                query_texts=[query_text],
                n_results=3
                # include = ["documents", "metadatas", "distances"] # Optional: Request specific data
            )

            # Print results clearly
            if results['documents'] and results['documents'][0]:
                for idx, doc in enumerate(results['documents'][0]):
                    meta = results['metadatas'][0][idx]
                    dist = results['distances'][0][idx] if results['distances'] else "N/A"

                    # Format metadata for display
                    target_text = meta.get('target', 'N/A')

                    print(f"   Match {idx+1} (Dist: {dist}):")
                    print(f"     Src: {doc}")
                    print(f"     Tgt: {target_text}")
            else:
                print("   No matches found.")


if __name__ == "__main__":
    main()
