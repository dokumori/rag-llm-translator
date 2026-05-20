# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [5.1.0] - 2026-05-20

### Added
- **BATS shell test suite**: introduced [BATS](https://github.com/bats-core/bats-core) as the shell script testing framework, added as Git submodules under `tests/bats/` (core, support, assert). A `tests/shell/test_helper.bash` file provides common setup shared across all test files.
- **`tests/shell/`**: comprehensive BATS test files covering `bin/common.sh`, `bin/manage-backup.sh`, `bin/setup_post_processing.sh`, `bin/translate.sh`, and `bin/run_tests.sh`.
- **`bin/run_bash_tests.sh`**: new script that discovers and runs all `.bats` files in `tests/shell/`.
- **`bin/lib/env_helpers.sh`**: new shared helper library extracted from `bin/setup_post_processing.sh`, containing the `_build_plugin_lines` and `_patch_env` functions so they can be sourced and unit-tested independently.
- **`bin/lib/model_config.py`**: new Python module centralising model-list loading and merging logic (previously duplicated as inline heredocs in `bin/translate.sh` and `bin/eval_quality.sh`). Provides a CLI interface (`list --format names|lookup`) consumed by both scripts.
- **`tests/unit/test_model_config.py`**: pytest unit tests for `bin/lib/model_config.py`.

### Changed
- **`bin/translate.sh`** and **`bin/eval_quality.sh`**: replaced duplicated inline Python heredocs (`load_merged_models`) with calls to `bin/lib/model_config.py`, eliminating ~40 lines of duplicated logic from each script.
- **`bin/setup_post_processing.sh`**: `_build_plugin_lines` and `_patch_env` are now sourced from `bin/lib/env_helpers.sh` rather than defined inline.

### Fixed
- **`bin/common.sh` — `list_available_langs`**: replaced a fragile character-length heuristic (`[ ${#dir_name} -gt 5 ]`) with a proper BCP-47-compliant `is_langcode` regex function, preventing false positives from non-language directory names.
- **`bin/common.sh` — `list_available_langs`**: corrected the `find` depth from `maxdepth 2` to `maxdepth 1`, so the function only considers `.po` files directly inside a language directory rather than recursing into subdirectories.

## [5.0.3] - 2026-05-18

### Fixed
- **`rag-proxy` / `app.py`**: o-series (o1, o3, o4) and GPT-5 family models reject `temperature≠1` with a hard 400 error. While LiteLLM's `drop_params` setting is intended to handle this automatically, it is unreliable for these models in practice (documented community reports of it failing to drop `temperature` even when set). Added an explicit fallback in `app.py` that omits `temperature` from the upstream call whenever the requested model ID starts with an o-series or `gpt-5` prefix, providing a version-independent safety net regardless of LiteLLM behaviour.
- **`rag-proxy` / `app.py`**: o-series and GPT-5 family models also require `max_completion_tokens` instead of `max_tokens` — OpenAI rejects `max_tokens` for these models with a 400 error. Following the same lesson as the `temperature` fix, LiteLLM is **not** relied upon to translate this automatically. The proxy now explicitly sends `max_completion_tokens` for reasoning models and `max_tokens` for all others.
- **`config/litellm/config.yaml`** and **`config.example.yaml`**: added `litellm_settings: drop_params: true` as a secondary guard.
- **`bin/setup.sh`**: auto-generated `config.yaml` now includes `drop_params: true` from the start.
- **`tests/unit/test_rag_proxy.py`**: added regression tests pinning the temperature-omission and `max_completion_tokens` behaviour for all known o-series and GPT-5 model ID prefixes.

## [5.0.2] - 2026-05-18

> **Upgrade:** `docker compose pull chroma && docker compose build rag-proxy toolbox && docker compose up -d`

### Changed
- **ChromaDB 1.5.8 → 1.5.9**: bumped the `chromadb/chroma` Docker image and the `chromadb` pip dependency (pinned in `rag-proxy` and `toolbox`) to v1.5.9. This is a patch release — no API changes, no data migration required.

## [5.0.1] - 2026-05-18
### Changed
- **README.md** Re-organised and rewrote the content based on the recent changes to the setup and execution process following the introduction of the system menu.


## [5.0.0] - 2026-05-18

> **Upgrade:** Re-run `bash bin/setup.sh` to regenerate your `.env` and `config/litellm/config.yaml`, then `docker compose up -d --build`.

> **Migration for existing users:** The simplest approach is to re-run `bash bin/setup.sh`. If you prefer to migrate manually, remove `COMPOSE_PROFILES=gateway` and `LLM_API_TOKEN` from your `.env` file. The gateway is now always required and per-model API keys are read from `config/litellm/config.yaml`. If your `LLM_BASE_URL` pointed directly at a provider (e.g. `https://api.openai.com/v1`), change it to `http://litellm:4000/v1` and add the corresponding entry to `config/litellm/config.yaml`.

### Added
- **Custom OpenAI-compatible endpoints via Gateway:** Users can now route amazee.ai, vLLM, and any OpenAI API-compatible endpoint through the built-in LiteLLM gateway. This enables switching freely between a custom endpoint and Anthropic/Google/OpenAI/Mistral models without changing `.env` or restarting services.
- **Ollama via Gateway:** Ollama (local models on the host machine) can now be routed through
  the LiteLLM gateway alongside cloud providers, using `ollama/<model>` as the provider prefix.
- **`bin/setup.sh`** — two new provider options in Gateway mode:
  - `Custom` — prompts for model name, remote model ID, base URL, and API key; generates
    the `openai_like/` block in `config/litellm/config.yaml` and the model entry in `models.json`.
  - `Ollama` — prompts for model name(s); auto-sets `OLLAMA_BASE_URL` in `.env`; warns
    Linux users about the `OLLAMA_HOST=0.0.0.0` and `extra_hosts` requirements.
- **`LLM_MAX_TOKENS`** — new environment variable (default: `4096`) that controls the maximum output tokens sent to the LLM. Previously this was hardcoded to `1000`, which caused truncation errors with responses of verbose models like Gemini. Set a higher value in `.env` if you encounter `JSONDecodeError` or `KeyError` on truncated LLM output.

### Removed
- **Direct mode** — connecting `rag-proxy` directly to a remote LLM provider is no longer supported. All LLM traffic now routes through the **LiteLLM gateway**, which is a required service.
  - Removed the "Direct" option from `bin/setup.sh`.
  - Removed `COMPOSE_PROFILES` from the generated `.env` — the gateway starts automatically with `docker compose up -d`.
  - Removed `LLM_API_TOKEN` from the generated `.env` — API keys are managed per-model in `config/litellm/config.yaml`.
  - Removed `omit_temperature` and `use_max_completion_tokens` model flags — LiteLLM normalises provider-specific parameter differences (temperature, `max_tokens` vs `max_completion_tokens`) transparently, so these workarounds are no longer needed in `app.py`.
  - Removed the `_flags_note` comment from `config/models/models.json` and `config/models/custom/models.example.json`.

### Changed
- **`docker-compose.yml`**:
  - `litellm` service is no longer optional (no more `profiles: [gateway]`). It now starts with every `docker compose up -d`. `rag-proxy` and `toolbox` services declare `depends_on: litellm` with health checks.
  - Replaced primitive port-based health checks (reading `/proc/net/tcp`) with curl-based HTTP health checks for `rag-proxy` (`/health`) and `litellm` (`/health`), providing true application-level readiness verification.
  - Removed redundant explicit `environment` declarations for variables already loaded via `env_file: .env`; replaced with explanatory comments pointing to `.env.defaults` for reference.
- **`.env.defaults`**: `LLM_BASE_URL=http://litellm:4000/v1` is now the canonical default.
- **`bin/setup.sh`** (renamed from `bin/initial_setup.sh` — the old name implied a one-time action, but the script is designed to be re-run whenever configuration changes):
  - The custom endpoint wizard now supports **multiple endpoints** in a single run. After configuring each endpoint, users are asked "Add another?". Environment variables use indexed names (`CUSTOM_LLM_BASE_URL_1`, `CUSTOM_LLM_API_KEY_1`, etc.).
  - Endpoints that share the same base URL and API key are deduplicated: `config.yaml` entries point to a shared env var pair instead of generating redundant variables in `.env`.
  - After completing custom endpoint setup, a note is displayed pointing users to the config files and `docs/8_multi_llm_support.md` for manual editing.
  - Fixed empty-array expansion under bash 3.2 (`set -u`) when no custom endpoints are configured.
  - Corrected the connection-mode description that still referenced the removed "Direct" option.
- **`bin/system_menu.sh`** — the "Ingest TM / Glossary" option now automatically runs `check_db.py` after ingestion completes, displaying a ChromaDB collection summary so users can immediately verify what was indexed.
- **`rag-proxy` / `app.py`** — RAG lookup log messages now include the collection name when reporting hits and misses, making it easier to trace which collection (TM or Glossary) produced a result.
- **`docs/8_multi_llm_support.md`**: rewritten to describe the gateway-only architecture. "Direct Mode" section removed. Updated to document multi-endpoint support and indexed env vars.
- **`README.md`**: updated to reflect gateway-only architecture.
- **`config/litellm/config.example.yaml`** — updated custom endpoint example to use indexed env var naming.


## [4.3.0] - 2026-05-14

### Added
- **`bin/system_menu.sh`** — new interactive CLI system menu that serves as the primary entry point for the project:
  - Detects environment state on each render (missing `.env`, Docker not running, empty ChromaDB collections, missing source data) and displays contextual warning/info hints.
  - Shows preparation instructions before running commands that require files to be in place (e.g. ingest, translate, evaluate).

## [4.2.2] - 2026-05-13

### Fixed
- **`po_translator`** — hardened to handle Haiku 3.5's tendency to return extra array items:
  - **Hardened LLM prompt**: user message now states the exact required count and instructs the model not to split a single input into multiple elements.
  - **Count-mismatch errors are now retriable**: wrong-count parse failures were previously non-retriable; they now retry within the existing `max_retries` loop with exponential back-off.
  - **Lenient trim for over-count responses**: surplus tail items are trimmed and logged as a warning rather than failing the batch. Responses with fewer items than expected still fail hard.
- **`rag-proxy` — dynamic output format instruction**: `FORMAT_INSTRUCTION` replaced with `_format_instruction(item_count)` so the system prompt includes the exact expected element count per request.

## [4.2.1] - 2026-05-13

### Fixed
- **`tests/unit/test_rag_proxy.py`**: fixed `test_models_config_caching` which was broken by a stale assertion. The `@functools.lru_cache` decorator was intentionally removed from `get_models_config` in a previous release (to allow hot-reloading of `custom/models.json` without restarting the container), but the corresponding test was not updated at the time. Replaced with `test_models_config_returns_model_list`, which patches `load_models_config` directly and verifies the correct list is returned.

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
