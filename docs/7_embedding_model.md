# Embedding Model Configuration

By default the RAG pipeline uses **`BAAI/bge-large-en-v1.5`** as its text embedding model. This guide explains how to use a different model, what requirements a model must meet, and how to switch models safely when data has already been ingested.

## Model Requirements

A compatible model must satisfy all of the following:

1. **No query/passage prefix required** — The model must produce meaningful embeddings from raw text without needing a `query:` or `passage:` prefix. Models in the `intfloat/e5-*` and `intfloat/multilingual-e5-*` families are **not supported** for this reason — they require distinct prefixes for queries vs. documents, which would require changes throughout the ingestion and query code.

2. **Compatible with `SentenceTransformerEmbeddingFunction`** — The model must be loadable by ChromaDB's built-in `SentenceTransformerEmbeddingFunction` (i.e. a HuggingFace model compatible with the `sentence-transformers` library).

3. **Available on HuggingFace Hub** — The model is downloaded at setup time via `sentence-transformers`. It must be publicly accessible, or you must configure HuggingFace authentication.

> [!WARNING]
> The application enforces these requirements at startup. If a blocked model is configured, `rag-proxy` will refuse to start with a clear error message.

## Tested Compatible Models

The following models are known to be compatible with this application's requirements:

| Model | Dimensions | Notes |
|:------|:-----------|:------|
| `BAAI/bge-large-en-v1.5` | 1024 | **Default.** English-optimised, high retrieval quality. |
| `BAAI/bge-base-en-v1.5` | 768 | Smaller and faster. Good for resource-constrained environments. |
| `BAAI/bge-small-en-v1.5` | 384 | Smallest BGE variant. Best for low-memory setups. |
| `sentence-transformers/all-MiniLM-L6-v2` | 384 | Lightweight and general-purpose. |
| `sentence-transformers/all-mpnet-base-v2` | 768 | Strong general-purpose model. |
| `sentence-transformers/multi-qa-mpnet-base-dot-v1` | 768 | English-only. Trained specifically for semantic search; good retrieval quality. |
| `sentence-transformers/all-distilroberta-v1` | 768 | English-only. Lighter than mpnet; good balance of speed and quality. |

> [!NOTE]
> This is not an exhaustive list. Any model meeting the requirements above can be used. The default `BAAI/bge-large-en-v1.5` is recommended for production use due to its strong English retrieval performance.
>
> **Avoid multilingual models** (e.g. `paraphrase-multilingual-*`, `BAAI/bge-m3`). The RAG pipeline embeds English source strings and compares them against each other — multilingual models distribute their capacity across many languages, which makes them less effective at discriminating between similar English strings and typically produces worse retrieval quality for this use case.

## Known Incompatible Models

| Model Family | Reason |
|:-------------|:-------|
| `intfloat/e5-*` | Requires `query:` / `passage:` prefixes |
| `intfloat/multilingual-e5-*` | Requires `query:` / `passage:` prefixes |

## How the Model is Managed

The embedding model is **not baked into the Docker image**. Instead, it is downloaded once into a bind-mounted directory on your host machine (`data/cache/huggingface/`) and reused across container restarts and rebuilds. This means:

- `docker compose build` is fast (no model download at build time)
- Switching models does **not** require a full image rebuild — only a re-download
- The model files are visible and inspectable in `data/cache/huggingface/` on your host

The `rag-proxy` container reads the model from this directory at startup with `HF_HUB_OFFLINE=1` — no internet access is required once the model has been downloaded.

## First-Time Setup

> [!IMPORTANT]
> Run `docker compose build` first. The download script runs inside the `rag-proxy` image, which must exist before it can be used.

The default model is downloaded automatically by `bin/initial_setup.sh`. If you skipped that step or need to re-download:

```bash
bin/download-model.sh                          # re-downloads EMBEDDING_MODEL_NAME from .env
```

If you want to download a specific model:
```bash
bin/download-model.sh BAAI/bge-base-en-v1.5   # downloads a specific model
```

## Switching Models

> [!CAUTION]
> Switching models after data has already been ingested requires wiping and re-ingesting all ChromaDB collections. Vectors produced by different models are not compatible — mixing them produces meaningless search results.

Use the orchestrated switch script to handle this safely:

```bash
bin/switch-embedding-model.sh BAAI/bge-base-en-v1.5

bin/switch-embedding-model.sh BAAI/bge-base-en-v1.5 -y   # skip confirmation prompts
```

The script will:

1. Validate the model against the blocklist
2. Ask for confirmation before making any changes
3. **Back up** the current ChromaDB state to `data/backups/`
4. **Wipe** all ChromaDB collections — before touching `.env`, so any failure leaves the system in a consistent state
5. Update `EMBEDDING_MODEL_NAME` in `.env`
6. Reset RAG thresholds to permissive defaults (`0.4`)
7. Download the new model into `data/cache/huggingface/`
8. Restart `rag-proxy` to pick up the new configuration

> [!NOTE]
> If the download step (7) fails, the script automatically rolls back the `EMBEDDING_MODEL_NAME` change in `.env`. The collections are already wiped at that point, so you will need to re-ingest regardless — but `rag-proxy` will be able to start cleanly.

After the switch completes, follow these steps in order:

```bash
bin/ingest.sh                                              # 1. re-ingest all data

docker compose up -d --build --force-recreate rag-proxy    # 2. rebuild to clear old logs

bin/translate.sh                                           # 3. dry-run to generate fresh RAG logs

bin/analyse.sh                                             # 4. recalibrate thresholds
```

### Why Thresholds Are Reset

RAG thresholds (`TM_THRESHOLD`, `GLOSSARY_THRESHOLD`) are cosine distance values calibrated specifically for the default model's distance distribution. A different model produces different distributions, so the existing thresholds will be too strict or too permissive. The switch script resets them to `0.4` (a broad, permissive default) so queries don't silently fail while you recalibrate.

See [docs/3_RAG_performance_analysis.md](3_RAG_performance_analysis.md) for the recalibration procedure.

## Safety Guardrails

The system enforces model consistency automatically to prevent silent data corruption:

### Startup Mismatch Check

When `rag-proxy` starts, it checks whether any existing ChromaDB collection was ingested with a different model than the one currently configured. If a mismatch is detected, the process **exits immediately** with a clear error:

```
❌ MODEL MISMATCH detected in collection 'app_tm'.
   Ingested with : 'BAAI/bge-large-en-v1.5'
   Current config: 'sentence-transformers/all-MiniLM-L6-v2'
...
To switch models safely:
  bin/switch-embedding-model.sh sentence-transformers/all-MiniLM-L6-v2
```

### Collection Metadata Stamping

Every collection is stamped with the `embedding_model` name at creation time. This is what allows the mismatch check to work — the model name travels with the data, not just with the configuration.

### Backup Model Validation

When restoring a backup, `bin/manage-backup.sh` extracts the model name from the backup filename and compares it to the current `EMBEDDING_MODEL_NAME`. If they differ, it warns you and requires explicit confirmation before proceeding.

Each backup also generates a `.meta.txt` sidecar file (e.g. `chroma_backup_20260508_163000_bge-large-en-v1.5.meta.txt`) documenting the model and threshold values at the time of the backup.

## Troubleshooting

### `rag-proxy` stuck in a mismatch dead-loop

If `rag-proxy` refuses to start with a MODEL MISMATCH error and you cannot run `bin/switch-embedding-model.sh` because `toolbox` is also down (it depends on `rag-proxy` being healthy), you can break out of the loop manually:

**Option A — re-run the switch script.** The script uses a disposable `rag-proxy` container for the collection wipe, so it does not require `toolbox` to be running:

```bash
bin/switch-embedding-model.sh <model-in-env> -y
```

Replace `<model-in-env>` above with whatever `EMBEDDING_MODEL_NAME` is currently set to in `.env`.

**Option B — delete collections manually**, then restart:

```bash
# 1. Wipe all collections using a disposable container
docker compose run --no-deps --rm \
    -e CHROMA_HOST=chroma -e CHROMA_PORT=8000 \
    rag-proxy \
    python3 -c "
import chromadb, os
client = chromadb.HttpClient(host='chroma', port=8000)
for col in client.list_collections():
    client.delete_collection(col.name)
    print(f'Deleted: {col.name}')
"

# 2. Restart rag-proxy (collections are gone — no mismatch possible)
docker compose up -d --force-recreate rag-proxy

# 3. Re-ingest
bin/ingest.sh
```
