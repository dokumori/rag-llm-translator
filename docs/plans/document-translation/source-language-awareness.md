# Plan: Source-Language Awareness (feature 1 of 3)

**Date:** 2026-10-01
**Decisions:** `document-translation-decisions.md` (Q34, Q36, Q40, Q40a,
Q41, Q42, Q58, Q58a, Q59, Q60). Where this plan and the log disagree, the
log wins; fix the plan.
**Release:** breaking change, **7.0.0** (existing collections must be
re-ingested).
**Next:** `collections-presets.md`, then `document-mode.md`. Do not start
either until this feature is released.

## Goal

Stop assuming English is the source language. A run declares its source
language; prompts, proxy matching, ingestion and cost estimation follow it.
English-source behaviour stays identical to today's.

## Out of scope

- Auto-detecting the source language (Q41).
- Glossary extraction from the Drupal DB: Drupal msgids are always English
  (Q40).
- Switching the embedding model. It already works via
  `bin/switch-embedding-model.sh` and needs a full re-ingest (Q34).
- Migrating existing collections (Q60). Users re-ingest.

## Tasks

Do them in this order: task 1 decides whether the rest is viable.

### 1. PyICU in both images (Q58, Q58a)

The checks in the decision log ran in throwaway containers. Now do it in
the real Dockerfiles (`services/toolbox/Dockerfile`,
`services/rag-proxy/Dockerfile`); both need it because the text module
(task 2) lives in `services/shared`.

- Builder stage: `libicu-dev pkg-config g++`. Runtime stage: `libicu72`
  (named package — this is the major-version pin).
- `PyICU==2.16.2` in its **own cached build step**, placed before the
  `requirements.txt` install so dependency bumps don't recompile it.
- Do **not** run a second `pip install --target /dependencies`: a second
  `--target` install re-resolves and overwrites the first. Install PyICU
  into its own directory (e.g. `/deps-icu`) and append it to every
  `PYTHONPATH` that keeps `/dependencies`: both Dockerfiles,
  `docker-compose.yml` (two services) and `bin/run_tests.sh`.
- Build for `linux/arm64` and `linux/amd64` (`docker buildx`).
- If the build or import fails on either platform, stop and reopen Q36.

### 2. Shared text module (Q36)

New `services/shared/src/core/text.py`, one engine, per-language data in
config, no per-language code paths:

- `words(text, lang)` and `sentences(text, lang)` via ICU `BreakIterator`.
- `stem(word, lang)` via snowballstemmer where the language has an
  algorithm (36 languages, no CJK); identity otherwise.
- Language data in a new `config/languages.yml` (committed): Snowball
  algorithm name, stop-list, abbreviations, chars-per-token, omission
  ratio band (used by feature 3). Unknown language → identity stemming,
  empty stop-list, a warning, and "unknown" where a language is reported.
- Supported languages per embedding model (Q42) in the same file, keyed by
  model name.

**English regression check before going further:** the proxy tokenises
today with `re.findall(r'\w+', …)` (`services/rag-proxy/src/app.py`, `has_shared_stems`).
ICU word breaking differs on apostrophes, underscores and some digits.
Run both tokenisers over the glossary and TM sources plus the proxy's
recent queries and compare guardrail decisions. If any decision changes,
stop and raise it — don't pick a workaround silently.

### 3. Source language in the request

- `--source-lang` (default `en`) on `bin/translate.sh` →
  `translate_runner.py` → `po_translator.py` (Q41).
- Payload envelope: the proxy accepts today's JSON array **or** an object
  `{"items": [...], "source_lang": "en"}`. Missing field → `en`. This
  envelope is where features 2 and 3 add their optional fields (Q51).
  Unknown top-level keys are ignored with a debug log.

### 4. Prompts (Q40.1)

- `config/prompts/generic.md:2`: "from English" → "from `{source_lang}`".
  Substitute the language name in `get_system_prompt_from_md`.
- `ja.md` and custom prompts: no change needed (no "English" source
  wording in `ja.md`). Docs say custom prompts may use `{source_lang}`.
- `judge_evaluation.md` mentions English words in Japanese text; that's
  about content, not the source language. Leave it.

### 5. Proxy matching (Q40.2)

- Replace `_stemmer`, `simple_stem`, `STOP_WORDS` and `has_shared_stems`
  in `app.py` with `core.text` calls using the request's source language.
- Lookups filter on `source_langcode` **and** `target_langcode`.
- Context filtering uses one key, `context`, for both collections
  (`_process_collection` no longer needs `context_meta_key`).

### 6. Entry schema and ingestion (Q40a, Q59)

New metadata, both collections:

```json
{"source_langcode": "en", "target_langcode": "ja", "target": "作成日", "context": ""}
```

TM entries also keep `file`. The source text stays the Chroma document.
`source_original` is dropped; TM `msgctxt` becomes `context`.

- `ingest.py` / `bin/ingest.sh`: `--source-lang` (default `en`).
- `generate_content_hash` includes the source language.
- At ingestion, warn when the source language isn't in the embedding
  model's supported list (Q40a, Q42).
- Other readers of the old keys must move too. `grep -E
  'langcode|msgctxt|source_original'` currently hits: `core/paths.py`,
  `core/utils.py`, `po_translator.py`, `ingest_client.py`,
  `evaluate_blind_test.py`, `extract_glossary_from_db.py`, `check_db.py`,
  `estimate_cost.py`, `translate_runner.py`, `bin/common.sh`,
  `bin/ingest.sh`, `bin/system_menu.sh`, `bin/setup_post_processing.sh`,
  `bin/translate.sh`. Many of these mean the *run's* target language
  (`langcode` as a CLI value), not the metadata key — change only
  metadata uses.

### 7. Old collections fail loudly (Q60)

- At proxy startup, next to `_validate_embedding_model_consistency`,
  read one entry per collection. Old format (no `target_langcode`) →
  log an error naming the re-ingest command (`bin/ingest.sh … --reset`)
  and refuse lookups on that collection. Never return silently empty
  results.
- Ingest API: `langcode` → `target_langcode` in `/api/ingest/reset` and
  `/api/ingest/languages`, no alias. Update `ingest_client.py`. The
  unmerged `tmgmt-integration` branch will need the same rename.

### 8. Cost estimator (Q40.4)

`estimate_cost.py` takes the source language and reads chars-per-token
from `config/languages.yml`, replacing the constant `CHARS_PER_TOKEN`
(`estimate_cost.py:72`). English keeps 4.0.

## Tests

- **Unit:**
  - `core.text`: expected word/sentence splits for en, de, ja (e.g.
    作成日を表示します → `['作成', '日', 'を', '表示', 'し', 'ます']`);
    assert ICU major version 72; unknown language path.
  - Proxy: payload array and envelope; filters on both language keys;
    old-format collection refused; prompt substitution.
  - Ingest: new metadata shape; ID hash includes source language; same
    text in two source languages → two IDs; coverage warning.
  - Estimator: chars-per-token per language.
- **Bats:** `--source-lang` on `translate.sh` and `ingest.sh`.
- **Integration (scratch stack):** ingest a small glossary and TM with the
  new schema; dry-run lookup returns hits; an old-format collection
  triggers the startup error.

## Acceptance

- English-source output identical to today's. Concretely: on the scratch
  stack, capture the proxy's system prompts for a fixed set of UI strings
  on `main`, then on this branch after re-ingesting the same data; they
  must be byte-identical (`{source_lang}` renders as "English").
- Images build and the suite passes on arm64 and amd64.
- Full test suite green (baseline 435 tests plus the new ones).

## Docs and changelog

- `CHANGELOG.md` `[Unreleased]`, one entry each: source-language flag;
  new entry schema (**breaking**, re-ingest steps); ingest API rename
  (**breaking**); old-collection startup check; PyICU dependency.
- Docs: `docs/1_architecture.md` (entry schema), `docs/6_chromadb_admin.md`
  (re-ingest), `docs/7_embedding_model.md` (supported languages),
  `docs/9_cost_estimation.md` (per-language chars-per-token), README flag
  table.
