'''
Checks if the DB is populated with the glossary / translation memory.
If empty, use ingest.py to populate the DB.

docker compose exec toolbox python3 /app/src/check_db.py
'''

import chromadb
import os

# Connect to the chroma service defined in docker-compose
# We use the hostname 'chroma' and port 8000 as per your compose file
client = chromadb.HttpClient(host='chroma', port=8000)

try:
    # Check TM Collection
    tm_col = client.get_collection("app_tm")
    count = tm_col.count()
    print(f"✅ Collection 'app_tm' exists.")
    print(f"📊 Total items in TM: {count}")
except Exception as e:
    print(f"❌ Collection 'app_tm' does NOT exist: {e}")

try:
    # Check Glossary Collection
    gloss_col = client.get_collection("app_glossary")
    count = gloss_col.count()
    print(f"✅ Collection 'app_glossary' exists.")
    print(f"📊 Total items in Glossary: {count}")
except Exception as e:
    print(f"❌ Collection 'app_glossary' does NOT exist: {e}")
