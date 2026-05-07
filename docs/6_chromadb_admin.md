# ChromaDB Admin UI

The project includes **[chromadb-ui](https://github.com/BlackyDrum/chromadb-ui)**, a lightweight web-based admin interface for browsing and querying the ChromaDB vector database. It provides a visual way to inspect the `app_glossary` and `app_tm` collections without writing code or running CLI scripts.

The Docker image is ~30–50MB (nginx-alpine + static files).

## Starting the Admin UI

The admin UI is included in `docker-compose.yml` and starts automatically with the rest of the stack:

```bash
docker compose up -d --build
```

Once running, open **http://localhost:3001** in your browser.

## Connecting to ChromaDB

When the UI first loads, it will ask for connection details. Use the following values:

| Field | Value |
|-------|-------|
| **Server URL** | `http://localhost:8000` |
| **Tenant** | `default_tenant` |
| **Database** | `default_database` |

The server URL corresponds to the ChromaDB port exposed from the `chroma` container to your host machine (configured via `CHROMA_PORT` in `.env`). The tenant and database are ChromaDB's built-in defaults.

> [!NOTE]
> **CORS**: The `chroma` service in `docker-compose.yml` is pre-configured with `CHROMA_SERVER_CORS_ALLOW_ORIGINS` to allow requests from `localhost:3001` and the hosted GitHub Pages UI. If you change the UI port or encounter "Network Error", verify this setting matches your setup.

## What You Can Do

### Browse Collections
View all collections in the database (e.g. `app_glossary`, `app_tm`) along with their document counts.

### Inspect Documents
Browse individual documents stored in each collection. Each document includes:
- **Document text** — the source string that was embedded
- **Metadata** — associated fields such as `target` (translation), `langcode`, `note`, `msgctxt`, and `source_file`

### Filter by Metadata
Use the built-in metadata filter builder to query documents by their `langcode` or other metadata fields, helping you verify what data has been ingested for each target language.

### Run Similarity Searches
Enter a query string and see the closest matches ranked by distance score. This is useful for:
- Verifying that the correct glossary terms or TM entries are being retrieved
- Debugging RAG lookup results
- Testing how different phrasings affect retrieval quality

### Additional Features
- Create, rename, clone, and delete collections
- Edit documents, metadata, and embeddings
- Export the current table view as CSV
- Import/upsert JSON records
- View collection metrics and quality audit findings

## Relationship to Existing CLI Tools

The admin UI complements the existing command-line tools:

| Tool | Purpose | How to run |
|------|---------|------------|
| `check_db.py` | Quick stats — collection sizes and per-language breakdown | `docker compose exec toolbox python3 /app/src/check_db.py` |
| `check_rag.py` | Peek at records and run sample vector queries | `docker compose exec toolbox python3 /app/src/debug/check_rag.py` |
| `debug_rag.py` | Batch query with hardcoded test sentences | `docker compose exec toolbox python3 /app/src/debug/debug_rag.py` |
| **chromadb-ui** | Visual browsing, filtering, and ad-hoc queries | http://localhost:3001 |

## Notes

- **chromadb-ui** is an [open-source community project](https://github.com/BlackyDrum/chromadb-ui) (MIT license) and is not an official Chroma product.
- The UI is a client-side application — all connections to ChromaDB are made from your browser, not from within the Docker network.
- The admin UI is read-only for practical purposes; data ingestion and deletion should continue to use `ingest.py` and the ingestion pipeline.
