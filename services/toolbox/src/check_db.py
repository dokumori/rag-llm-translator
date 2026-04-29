'''
Checks if the DB is populated with the glossary / translation memory.
If empty, use ingest.py to populate the DB.

docker compose exec toolbox python3 /app/src/check_db.py
'''

import chromadb
from collections import Counter
from core.config import Config
from infrastructure import get_chroma_client

# Connect to the chroma service defined in docker-compose
# We use the hostname 'chroma' and port 8000 as per your compose file
client = get_chroma_client()

def check_and_print_stats(collection_name: str, display_name: str) -> None:
    try:
        col = client.get_collection(collection_name)
        count = col.count()
        print(f"✅ Collection '{display_name}' exists.")
        print(f"📊 Total items in {display_name}: {count}")
        
        if count > 0:
            results = col.get(include=["metadatas"], limit=count)
            metadatas = results.get("metadatas", [])
            
            if metadatas:
                # Count occurrences per langcode, defaulting to 'unknown' if missing
                lang_counts = Counter(
                    str(meta.get("langcode", "unknown")).strip() 
                    for meta in metadatas if meta is not None
                )
                
                print("   Breakdown by language:")
                for lang, freq in lang_counts.most_common():
                    print(f"   - {lang}: {freq}")
    except Exception as e:
        print(f"❌ Collection '{display_name}' does NOT exist: {e}")

# Check TM Collection
check_and_print_stats(Config.TM_COLLECTION, 'app_tm')
print()

# Check Glossary Collection
check_and_print_stats(Config.GLOSSARY_COLLECTION, 'app_glossary')
