# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
(none)

## [4.2.0]
### Added
- **`bin/initial_setup.sh`** — fully rewritten as an interactive setup wizard:
  - **Mode selection**: choose between three LLM connection modes:
    - *Direct* — enter a custom OpenAI-compatible base URL and API token (e.g. amazee.ai, vLLM, Mistral La Plateforme).
    - *Gateway* — use the built-in LiteLLM proxy for Anthropic, Google (Gemini), OpenAI, or Mistral. Prompts for each provider's API key (hidden input) and auto-generates `config/litellm/config.yaml` and `config/models/custom/models.json` containing only the selected providers' models.
    - *Local (Ollama)* — auto-configures `LLM_BASE_URL=http://host.docker.internal:11434/v1` with no API token required.
  - **Gateway auto-start**: in Gateway mode, optionally writes `COMPOSE_PROFILES=gateway` to `.env` so the LiteLLM container starts with every `docker compose up`.
  - **`.env` backup**: prompts to back up any existing `.env` to `.env-backups/.env-YYYYMMDD-HHMMSS` before overwriting, making the script safe to re-run without losing credentials.
  - **Confirmation summary**: displays all chosen settings before writing any files, with an abort option.
- **CHANGELOG.md descriptions**: Added 'Upgrade' for versions that require rebuild and other operations for the changes to take effect.



## [4.1.0] - 2026-05-11

> **Upgrade:** `docker compose build rag-proxy && docker compose up -d`

### Added
- **Multi-LLM provider support**: the system now supports Anthropic (Claude), Google (Gemini), and OpenAI reasoning models (o-series, GPT-5) in addition to existing OpenAI-compatible providers.
  - **`docker-compose.yml`**: optional `litellm` service added under the `gateway` Docker Compose profile (`docker compose --profile gateway up -d`). LiteLLM translates Anthropic and Gemini native APIs to the OpenAI format transparently, requiring zero code changes to `rag-proxy` or toolbox.
  - **`config/litellm/config.sample.yaml`**: sample configuration file for the LiteLLM gateway; pre-populated with commented-out model entries for all providers. Copy this file to `config/litellm/config.yaml`, then uncomment to activate individual models. 
  - **`config/models/models.example.json`**: added `gpt-4o`, `o4-mini`, and `o3-mini` model entries. Added `omit_temperature` and `use_max_completion_tokens` flags to support OpenAI reasoning models (o-series, GPT-5) that reject the `temperature` parameter and require `max_completion_tokens` instead of `max_tokens`.
  - **`docs/8_multi_llm_support.md`**: new documentation page covering direct mode (OpenAI-compatible endpoints), gateway mode (LiteLLM), per-provider setup, model flags, and troubleshooting.

### Changed
- **`rag-proxy` / `app.py`**: upstream API call now builds parameters dynamically from model-level flags rather than hardcoding `temperature=0` and `max_tokens`. This enables support for OpenAI o-series and GPT-5 models in direct-connection mode without requiring the LiteLLM gateway.
- **`README.md`**: replaced the "Known issues" section (o-series / GPT-5 broken) with a description of the two provider connection modes (direct and gateway). Added link to `docs/8_multi_llm_support.md`.
- **`docs/7_embedding_model.md`**: Added a note about how models calculate distances differently, the importance of calibration, and that some models may not be suitable for the purpose of this project.

## [4.0.0] - 2026-05-10

> **Upgrade:** `docker compose build && docker compose up -d`

### Added
- **`bin/manage-backup.sh`**: new script to create and restore timestamped `.tar.gz` snapshots of the ChromaDB Docker volume (`chroma_data`). Supports `--dump`, `--restore [<file>]`, and `--list` subcommands; the `chroma` container is paused during dump for a consistent snapshot.
- **`bin/switch-embedding-model.sh`**: new script to safely switch the text embedding model. It backs up the current ChromaDB state, deletes all collections, updates `EMBEDDING_MODEL_NAME` in `.env`, downloads the new model, and restarts `rag-proxy`.
- **`bin/download-model.sh`**: helper script to pre-download a HuggingFace embedding model into `data/cache/huggingface/`.
- **`services/shared/scripts/check_collection_model.py`**: utility that reports whether the model recorded in ChromaDB collection metadata matches the currently configured `EMBEDDING_MODEL_NAME`, with a clear mismatch warning.
- **`services/shared/scripts/delete_collections.py`**: low-level utility to delete ChromaDB collections directly (used by the switch workflow, bypassing `rag-proxy`).
- **`docs/7_embedding_model.md`**: comprehensive guide covering model requirements, tested compatible models, known incompatible model families, and the full model-switching workflow.
- **`docs/6_chromadb_admin.md`**: backup and restore section documenting `manage-backup.sh` usage.

### Changed
- **`initial_setup.sh`**: `EMBEDDING_MODEL_NAME` is now read from `.env.defaults` instead of being hardcoded, preventing configuration drift.
- **`rag-proxy`** (`infrastructure.py`): the default embedding model name is sourced from `.env.defaults` at runtime rather than hardcoded, ensuring a single source of truth.
- **`bin/analyse.sh`**: extended with a pre-flight model-consistency check that aborts analysis when a ChromaDB/env mismatch is detected, guiding operators toward re-ingestion.
- **`initial_setup.sh`**: removed the option to specify an embedding model at install time to reduce complexity; model selection is done post-install via `switch-embedding-model.sh`.
- **`README.md`**: updated setup instructions and embedding model guidance.

### Fixed
- **`rag-proxy`**: resolved issue where an outdated embedding model remained active in a running container after switching, due to stale shell-environment variables surviving `docker compose` restarts.
- **`check_db.py`**: now explicitly reports the active `EMBEDDING_MODEL_NAME` and highlights collection/env mismatches.

## [3.3.0] - 2026-05-08
(In the previous release, these changes were mistakenly left under 'unreleased')

> **Upgrade:** `docker compose build rag-proxy && docker compose up -d`
> The new `chromadb-ui` service starts automatically on port `3001`.

### Added
- **`chromadb-ui`**: lightweight web-based admin interface added as a Docker Compose service on port `3001` for visual browsing and querying of ChromaDB collections.
- **`docs`**: documentation for the ChromaDB Admin UI.
- **`rag-proxy`**: endpoint to list language codes stored in the glossary and TM collections.
- **`toolbox`**: `IngestClient` support for querying available languages from the vector DB.
- **`tests`**: ChromaDB stubs package for unit tests (replaces the `custom/` directory).
- Unit tests for the languages endpoint and for `--reset-only` scope flags.
- Custom plugin test discovery: plugin submodules can now ship their own `tests/` directories.

### Changed
- **`ingest.sh`**: reset flow now prompts for scope (TM / Glossary / All) and dynamically discovers available languages from the vector DB, with a filesystem fallback.
- **`chroma`**: config file mounted into the container for CORS pre-configuration.
- **`tests/pytest.ini`**: stub path updated from `custom` to `stubs`; plugin paths added.

## [3.2.1] - 2026-05-02

> **Upgrade:** `docker compose pull chroma && docker compose build toolbox && docker compose up -d`

### Changed
- **`docker-compose`**: bumped `chromadb/chroma` Docker image from `1.4.1` to `1.5.8` (Renovate).
- **`toolbox`**: updated `chromadb` Python package to `1.5.8` (Renovate).
- **`toolbox`**: updated `pytest` from `~8.3` to `~9.0` (Renovate).

## [3.2.0] - 2026-05-01

> **Upgrade:** `docker compose build && docker compose up -d`
> The toolbox image is significantly smaller in this release (~3 GB reduction); a full rebuild is required.

### Added
- **`rag-proxy`**: new `/api/ingest/*` endpoints (`reset`, `check-ids`, `add`) for remote ingestion.
- **`rag-proxy`**: new `/api/rag-lookup` endpoint for remote RAG context retrieval.
- **`toolbox`**: `IngestClient` HTTP wrapper for the rag-proxy ingestion API.
- Integration tests for the ingestion API (`test_ingest_api.py`).
- Integration tests for the RAG lookup API (`test_rag_lookup_api.py`).
- Renovate bot configuration (`renovate.json5`) for automated dependency updates across pip, Docker, and Docker Compose.

### Changed
- **`ingest`**: delegates embedding and ChromaDB writes to rag-proxy over HTTP instead of running locally.
- **`evaluate_blind_test`**: retrieves RAG context via `/api/rag-lookup` instead of importing the rag-proxy's `app` module.
- **`config.py`**: document that `custom/models.json` replaces (not merges) the base model list, and removed misleading `@dataclass` decorator.

### Fixed
- **`po_translator`**: LLM parse failures now fail fast instead of consuming retry attempts.
- **`rag-proxy`**: guard against empty `distances`/`metadatas` sublists from ChromaDB to prevent silent `IndexError`.
- **`evaluate_blind_test`**: initialise `models_list = []` before the `try` block to prevent `NameError` on missing config.
- **`evaluate_blind_test`**: avoid passing `response_format=None` explicitly to prevent SDK compatibility issues.
- **`post_process`**: `check_plugin_conflicts()` now runs after the `POST_PROCESSING_ENABLED` guard.
- **`analyse_logs`**: fix arithmetic error in deduplication log message.
- **`infrastructure`**: implemented thread-safe double-checked locking for singletons to prevent race conditions.

### Refactored
- **`extract_glossary_from_db`**: modularized the monolithic processing pipeline into testable phase helpers.
- **`rag-proxy`**: deduplicated TM and Glossary retrieval logic and replaced global client with `lru_cache`.
- **`ingest`**: adopted `add_mutually_exclusive_group()` for flags and added `.po` pre-flight validation.
- **`post_process`**: replaced `sys.exit()` in `main()` with returns to improve unit testability.
- **`translate_runner`**: removed redundant `TARGET_LANG` validation block.

### Removed
- `sentence-transformers` and `transformers` from toolbox requirements (~3 GB reduction in image size).


## [3.1.0] - 2026-05-01

> **Upgrade:** `docker compose build && docker compose up -d`

### Added
- **Token usage tracking**: prompt, completion, and total token counts are now accumulated across each translation and evaluation run, with a summary printed to the log and saved as a JSON file in the output directory.
- Pricing information (approximate for some) added to `models.json` for all supported models.
- Unit tests for the new token tracking module.
- Model pricing is fully config-driven via `models.json`.

### Changed
- Token tracking is integrated into both the translation pipeline and the LLM-as-a-Judge evaluation workflow.

## [3.0.0] - 2026-04-30

> **Upgrade:** `docker compose build toolbox && docker compose up -d`
> ⚠️ Breaking change: the external `gpt-po-translator` dependency has been replaced. Remove it from any scripts that called it directly.

### Added
- Support for plurals in `.po` files.
- Tests for the new custom `po_translator` and plural support logic.

### Changed
- **Breaking Change:** Replaced the external `gpt-po-translator` dependency with a lightweight, custom Python driver.
- Removed parts of default prompts that overlapped with the hard-coded formatting prompt to improve consistency.

### Removed
- Workarounds previously required to support `gpt-po-translator`.
- Tests related to the deprecated `gpt-po-translator`.
