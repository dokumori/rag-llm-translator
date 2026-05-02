# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [3.2.1] - 2026-05-02

### Changed
- **`docker-compose`**: bumped `chromadb/chroma` Docker image from `1.4.1` to `1.5.8` (Renovate).
- **`toolbox`**: updated `chromadb` Python package to `1.5.8` (Renovate).
- **`toolbox`**: updated `pytest` from `~8.3` to `~9.0` (Renovate).

## [3.2.0] - 2026-05-01

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

### Added
- **Token usage tracking**: prompt, completion, and total token counts are now accumulated across each translation and evaluation run, with a summary printed to the log and saved as a JSON file in the output directory.
- Pricing information (approximate for some) added to `models.json` for all supported models.
- Unit tests for the new token tracking module.
- Model pricing is fully config-driven via `models.json`.

### Changed
- Token tracking is integrated into both the translation pipeline and the LLM-as-a-Judge evaluation workflow.

## [3.0.0] - 2026-04-30

### Added
- Support for plurals in `.po` files.
- Tests for the new custom `po_translator` and plural support logic.

### Changed
- **Breaking Change:** Replaced the external `gpt-po-translator` dependency with a lightweight, custom Python driver.
- Removed parts of default prompts that overlapped with the hard-coded formatting prompt to improve consistency.

### Removed
- Workarounds previously required to support `gpt-po-translator`.
- Tests related to the deprecated `gpt-po-translator`.
