#!/usr/bin/env python3
"""
services/shared/scripts/check_collection_model.py

Checks whether any ChromaDB collection was ingested with a different embedding
model than the one currently configured (TARGET_MODEL env var).

Exit codes:
  0  — all collections are consistent (or no collections exist)
  2  — at least one collection has a mismatched embedding_model metadata value
  1  — could not connect to ChromaDB

Invoked by bin/switch-embedding-model.sh to detect a mid-switch state where
.env was already updated but the stale collections were never wiped.

Usage (inside a rag-proxy container):
  TARGET_MODEL="<your-embedding-model>" python3 /app/check_collection_model.py
"""

import os
import sys

import chromadb

host = os.environ.get("CHROMA_HOST", "chroma")
port = int(os.environ.get("CHROMA_PORT", 8000))
target_model = os.environ.get("TARGET_MODEL", "")

try:
    client = chromadb.HttpClient(host=host, port=port)
    collections = client.list_collections()
except Exception as exc:
    print(f"ERROR: Could not connect to ChromaDB at {host}:{port} — {exc}", file=sys.stderr)
    sys.exit(1)

for col in collections:
    meta = col.metadata or {}
    ingested_with = meta.get("embedding_model", "")
    if ingested_with and ingested_with != target_model:
        # Print a machine-parseable line for the shell script to read
        print(f"MISMATCH:{col.name}:{ingested_with}")
        sys.exit(2)

print("OK")
sys.exit(0)
