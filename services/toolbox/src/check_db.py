'''
Checks if the DB is populated with the glossary / translation memory.
If empty, use ingest.py to populate the DB.

docker compose exec toolbox python3 /app/src/check_db.py
'''

import chromadb
from core.config import Config
from infrastructure import get_chroma_client

# Connect to the chroma service defined in docker-compose
# We use the hostname 'chroma' and port 8000 as per your compose file
client = get_chroma_client()

try:
    # Check TM Collection
    tm_col = client.get_collection(Config.TM_COLLECTION)
    count = tm_col.count()
    print(f"✅ Collection 'app_tm' exists.")
    print(f"📊 Total items in TM: {count}")
except Exception as e:
    print(f"❌ Collection 'app_tm' does NOT exist: {e}")

try:
    # Check Glossary Collection
    gloss_col = client.get_collection(Config.GLOSSARY_COLLECTION)
    count = gloss_col.count()
    print(f"✅ Collection 'app_glossary' exists.")
    print(f"📊 Total items in Glossary: {count}")
except Exception as e:
    print(f"❌ Collection 'app_glossary' does NOT exist: {e}")
