# Plan: Collections and Presets (feature 2 of 3)

**Date:** 2026-10-01
**Decisions:** `document-translation-decisions.md` (Q20, Q21, Q23–Q27;
Q40a removes `context_key` from Q25). Where this plan and the log
disagree, the log wins; fix the plan.
**Prerequisite:** `source-language-awareness.md` released (entry schema,
payload envelope, `core.text`).
**Release:** additive, no re-ingest needed.

## Goal

Replace the hard-coded glossary/TM pair with user-defined collections and
named presets, selectable per run. Useful for UI translation on its own;
document mode (feature 3) builds on it.

## Out of scope

- Fixed collection "kinds" (Q21): `glossary` and `tm` are only built-in
  defaults to inherit from.
- Interactive setup of collections (Q24, later).
- Free-form prompt templates per collection (Q25: named formats only).
- Implementing the document-mode matchers. This feature only validates
  `match.document`; feature 3 implements it.

## Config

`config/rag/collections.yml`, git-ignored, with a committed
`collections.example.yml` (Q23):

```yaml
collections:
  app_glossary:
    base: glossary
  app_tm:
    base: tm
  drupal_core_terms:
    base: glossary
    threshold: 0.30
presets:
  default: [app_glossary, app_tm]
  docs: [drupal_core_terms, app_glossary, app_tm]
```

Built-in bases reproduce today's behaviour (Q24, Q25):

| Setting | `glossary` | `tm` |
|---|---|---|
| `source_format` | `csv` | `po` |
| `match.ui` | embedding + guardrail | embedding + guardrail |
| `match.document` | `lexical` | `[phrase, fuzzy]` |
| `threshold` | `GLOSSARY_THRESHOLD` | `TM_THRESHOLD` |
| `format` | `term_list` | `pairs` |

- A collection overrides any setting; unset settings come from `base`.
- `format` accepts only `term_list` and `pairs`.
- The guardrail is always on for embedding matching; not a setting.
- Built-in preset `none` = no lookup.
- Missing file → synthesise the default preset from `TM_COLLECTION` and
  `GLOSSARY_COLLECTION`, so nothing changes for existing users.
- Validation errors name the file, collection and field.

## Tasks

### 1. Registry loader

`services/shared/src/core/collections.py`: parse and validate the YAML,
apply bases, resolve a preset name or explicit list into ordered
`CollectionSpec` dataclasses. Used by proxy, ingestion, estimator and
`analyse_logs.py`. Thresholds and collection names come from
`core.config.Config`; nothing hard-coded.

### 2. Selection

- `bin/translate.sh` → `translate_runner.py` → `po_translator.py`:
  `--preset <name>` or `--collections a,b`, mutually exclusive. Neither →
  `default`, no prompt (Q23). `--skip-rag` keeps its meaning.
- Payload envelope (from feature 1) gains optional `preset` /
  `collections`. The proxy resolves them; unknown names → HTTP 400 listing
  valid names. `translate.sh` validates up front with the same message.

### 3. Proxy lookups

- `perform_rag_lookup` iterates the resolved specs instead of the two
  hard-coded blocks (`services/rag-proxy/src/app.py`).
- Prompt sections by `format` (Q26): all `term_list` hits under
  `<glossary_matches>`, all `pairs` hits under `<tm_matches>`, in preset
  order. Existing prompts keep working.
- Conflicts (Q27): when collections give different targets for the same
  source term, list all renderings in preset order and mark the first
  **preferred**. Only when a conflict exists, add one line to that section:
  use the preferred rendering unless the context clearly calls for another
  listed sense. Log every conflict.
- Each logged hit gains `"collection": <name>`; keep `"type"` for old log
  readers.
- `_validate_embedding_model_consistency` checks every registered
  collection.

### 4. Ingestion

`bin/ingest.sh` / `ingest.py`: `--collection <name>` targets any
registered collection; its `source_format` picks CSV or PO parsing. Reuse
the existing cleaning, dedup, `_is_suspicious_entry` and incremental load.
No flag → today's two collections. The interactive menu lists registered
collections.

### 5. Analysis and cost

- `analyse_logs.py` / `bin/analyse.sh`: stats and threshold
  recommendations per collection; fall back to `type` for old logs.
- `estimate_cost.py`: RAG overhead scales with the number of collections
  in the preset (today: one constant for two collections). Document the
  derivation in `docs/9_cost_estimation.md`.

## Tests

- **Unit:** loader (valid file; missing file → env fallback; unknown base;
  bad `format`; unknown preset; duplicate names; override inheritance);
  `perform_rag_lookup` with three mocked collections; section grouping by
  format; conflict listing and the conditional rule line; `collection` in
  log entries.
- **Bats:** `--preset`, `--collections`, both given → error, unknown name
  → error listing valid names; `ingest.sh --collection`.
- **Integration (scratch stack):** ingest a small CSV into a new
  collection; dry-run with a preset including it; the proxy log shows
  lookups on the selected collections only.

## Acceptance

- Without `collections.yml`, and with a file that only declares the two
  defaults, the `default` preset produces **byte-identical system
  prompts** to feature 1's for the same inputs (same capture method as
  feature 1).
- Full suite green.

## Docs and changelog

- `CHANGELOG.md` `[Unreleased]`, one entry each: collection registry and
  presets; `--preset`/`--collections`; `ingest.sh --collection`;
  per-collection analysis; conflict handling.
- New `docs/11_collections_and_presets.md` (`10_` is claimed by the
  unmerged `tmgmt-integration` branch); links from README and
  `docs/3_RAG_performance_analysis.md`.
