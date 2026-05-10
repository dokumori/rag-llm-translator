#!/usr/bin/env python3
"""
services/shared/scripts/delete_collections.py

Deletes ALL ChromaDB collections directly via the ChromaDB HTTP API.
Used exclusively by bin/switch-embedding-model.sh.

Exists separately from bin/ingest.sh --reset-all because during a model switch
rag-proxy is unhealthy, making the normal toolbox → rag-proxy path unavailable.
For normal resets, use bin/ingest.sh instead.

Exit codes:
  0  — success (including the case where no collections existed)
  1  — connection error

Usage (inside a rag-proxy container):
  python3 /app/delete_collections.py
"""

import os
import sys

import chromadb

host = os.environ.get("CHROMA_HOST", "chroma")
port = int(os.environ.get("CHROMA_PORT", 8000))

try:
    client = chromadb.HttpClient(host=host, port=port)
    collections = client.list_collections()
except Exception as exc:
    print(f"ERROR: Could not connect to ChromaDB at {host}:{port} — {exc}", file=sys.stderr)
    sys.exit(1)

if not collections:
    print("ℹ️  No collections found — nothing to delete.")
    sys.exit(0)

for col in collections:
    client.delete_collection(col.name)
    print(f"🗑️  Deleted: {col.name}")

print("✅ All collections deleted.")
sys.exit(0)
