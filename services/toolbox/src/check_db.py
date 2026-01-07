import chromadb
import os

# Connect to the chroma service defined in docker-compose
# We use the hostname 'chroma' and port 8000 as per your compose file
client = chromadb.HttpClient(host='chroma', port=8000)

try:
    # Check TM Collection
    tm_col = client.get_collection("drupal_tm")
    count = tm_col.count()
    print(f"✅ Collection 'drupal_tm' exists.")
    print(f"📊 Total items in TM: {count}")
except Exception as e:
    print(f"❌ Collection 'drupal_tm' does NOT exist: {e}")

try:
    # Check Glossary Collection
    gloss_col = client.get_collection("drupal_glossary")
    count = gloss_col.count()
    print(f"✅ Collection 'drupal_glossary' exists.")
    print(f"📊 Total items in Glossary: {count}")
except Exception as e:
    print(f"❌ Collection 'drupal_glossary' does NOT exist: {e}")
