# Implementation Plan: Multi-Collection RAG + Document Translation Mode

> **Superseded (2026-10-01)** by `source-language-awareness.md`,
> `collections-presets.md` and `document-mode.md`, built from
> `document-translation-decisions.md`. Kept for history only.

**Date:** 2026-07-22
**Status:** Draft for implementation
**Audience:** Implementing LLM (Opus) + human reviewer

This plan extends the RAG-LLM Translator with (a) user-defined vector DB
collections with presets, and (b) a *document mode* for translating
document-derived PO files (produced by po4a, translate-toolkit's html2po,
mdpo, sphinx-gettext, etc.) with cross-entry context, so web/documentation
content is translated coherently rather than string-by-string.

**Prerequisite:** the `tmgmt-integration` branch must be merged into `main`
before Stage 1 begins. It refactors shared modules this plan builds on
(`parse_translations` → `core/utils.py`, new `api_helpers.py`, new
`/api/v1/translate` Blueprint) and claims `docs/10_translation_api.md`.
Stage 1's per-request collection selection must also be exposed on
`/api/v1/translate` (body fields `rag_preset` / `rag_collections`, same
semantics as the proxy path). Stage 3's payload contract v2 should be
designed so the REST endpoint can later accept ordered segments with
`type` and `window` fields — that is the bridge to future TMGMT *content*
translation, which is out of scope for this plan.

Each stage is independently shippable and testable. **Do not start a stage
until the previous stage's acceptance criteria pass.** Within a stage,
follow the existing codebase conventions (logging style, docstrings,
type hints, test layout under `tests/unit` / `tests/integration` /
`tests/bats`).

---

## Design principles (apply to every stage)

1. **Language-neutral core.** No language-specific rules (register, 体言止め,
   formality) in Python or shell code. Language-specific guidance lives
   exclusively in prompt files under `config/prompts/`, resolved via the
   existing chain (custom/{lang}.md → {lang}.md → generic.md). Code may only
   say *what* something is ("this is a heading"); prompts say *how* to
   render it.
2. **Extraction-tool-agnostic.** The translator consumes document-ordered PO
   files. po4a / html2po / mdpo invocation stays **outside** the stack
   (documented, not embedded). Tool-specific metadata parsing is isolated in
   one adapter module (Stage 2).
3. **Backwards compatible at every stage.** Existing UI-string workflow
   (`bin/translate.sh` with default collections) must behave identically
   unless new flags/config are used. Existing env vars (`TM_COLLECTION`,
   `GLOSSARY_COLLECTION`, thresholds) remain honoured as the implicit
   default configuration.
4. **Owned payload contract.** The JSON contract between `po_translator.py`
   and the rag-proxy (`{"text", "context"}` items) is extended additively —
   new optional fields, never renamed/removed fields. The proxy must accept
   payloads without the new fields.
5. **Fail safe, mark fuzzy.** When validation cannot confirm a translation
   is structurally sound (markup mismatch, count mismatch), keep the source
   or mark the entry `fuzzy` — never write a suspect msgstr silently.
6. **Dry-run first.** Every new pipeline behaviour must be observable via
   the existing dry-run model path so it can be tested without API spend.

---

## Stage 1 — Collection registry and presets

**Goal:** Replace the hardcoded `app_tm` / `app_glossary` pair with a
user-extensible collection registry and named presets, selectable per run.

### Deliverables

1. **Config file** `config/rag/collections.yml` (create `config/rag/`),
   with a committed `collections.example.yml`. Schema:

   ```yaml
   collections:
     - name: app_tm            # ChromaDB collection name
       kind: tm                # tm | glossary — drives retrieval & formatting
       label: "Translation memory"
       threshold: 0.27         # per-collection distance threshold
       context_key: msgctxt    # metadata key used for context isolation
     - name: app_glossary
       kind: glossary
       label: "Glossary"
       threshold: 0.36
       context_key: context
   presets:
     default: [app_tm, app_glossary]   # preserves current behaviour
     none: []                          # translate with RAG infra but no lookup
   ```

   - If the file is absent, synthesize the equivalent registry from the
     existing env vars (`TM_COLLECTION`, `GLOSSARY_COLLECTION`,
     `TM_THRESHOLD`, `GLOSSARY_THRESHOLD`) so nothing breaks.
   - `kind` is mandatory and restricted to `tm` | `glossary`. It selects
     the existing per-kind behaviour in `_process_collection()` (context
     meta key default, guardrail, `format_fn`, XML section tag). Unknown
     kinds are a config error (fail fast with a clear message).

2. **Shared loader** in `services/shared/src/core/` (e.g. `collections.py`):
   parse + validate the YAML, resolve a preset name or explicit collection
   list into `[CollectionSpec]` dataclasses. Used by proxy, ingestion, and
   analysis. Validation errors must name the offending field.

3. **rag-proxy changes** (`services/rag-proxy/src/app.py`):
   - `perform_rag_lookup()` iterates over resolved `CollectionSpec`s instead
     of the two hardcoded blocks. Output grouping: one
     `<{name}_matches>` XML section per collection with hits (keep the
     existing `<glossary_matches>` / `<tm_matches>` tags for the two default
     collections to avoid disturbing calibrated prompts).
   - Per-request selection: accept `rag_preset` (string) or
     `rag_collections` (list of names) in the request body, or headers
     `X-RAG-Preset` / `X-RAG-Collections` (comma-separated). Body wins over
     header; absent → `default` preset. Reject unknown names with HTTP 400
     listing valid options.
   - Each entry in `rag_matches` log gains a `"collection": <name>` field
     (keep the existing `"type"` field = kind, for backwards compat).
   - Startup embedding-model consistency check
     (`_validate_embedding_model_consistency`) iterates all registered
     collections.

4. **Ingestion** (`services/toolbox/src/ingest.py`, `bin/ingest.sh`):
   - New flag `--collection <name>` to target any registered collection;
     the interactive menu lists registered collections with labels.
   - Kind determines the expected source format: `glossary` → CSV
     (source/target columns), `tm` → PO. Reuse the existing cleaning,
     dedup, `_is_suspicious_entry`, and incremental-load logic unchanged.
   - Default (no flag): current behaviour (both default collections).

5. **Fine-tuning helper** (`services/toolbox/src/analyse_logs.py`,
   `bin/analyse.sh`): group stats and threshold recommendations **by
   collection name** (fall back to `type` for old logs that lack the
   field). Report sections appear per collection.

6. **Client plumbing** (`bin/translate.sh`, `bin/lib/translate_helpers.sh`,
   `translate_runner.py`, `po_translator.py`): new flags
   `--rag-preset <name>` / `--rag-collections <a,b,c>` threaded through to
   the request body. `--skip-rag` keeps its current meaning and short-circuits
   as today.

7. **Docs:** new `docs/11_custom_collections.md` covering the YAML schema,
   preset usage, ingestion into custom collections, and per-collection
   threshold tuning; cross-link from README and `docs/3_RAG_performance_analysis.md`.

### Explicitly out of scope for Stage 1

Freeform/other collection kinds; document mode; any prompt changes.

### Acceptance criteria

- Unit tests: registry loader (valid file, missing file → env-var fallback,
  bad kind, unknown preset, duplicate names); `perform_rag_lookup` with a
  3-collection registry using a mocked Chroma client; log entries carry
  `collection`.
- Bats tests: `translate.sh --rag-preset`, `--rag-collections`, invalid
  name → error listing valid names; `ingest.sh --collection`.
- Integration (stack up): ingest a small custom glossary CSV into a new
  collection, run a dry-run translation with a preset including it, verify
  the proxy log shows lookups against all selected collections and none
  against unselected ones.
- Human check: run the existing demo flow **without** creating
  `collections.yml` — behaviour and output identical to pre-change.

---

## Stage 2 — Document-mode foundation: extractor adapter + ordered processing

**Goal:** Recognise document-derived PO files, normalise their metadata, and
process entries in document order. No prompt or retrieval changes yet —
this stage is about correct ordering, filtering, and metadata, all
verifiable via dry-run.

### Deliverables

1. **Extractor adapter module** `services/toolbox/src/doc_adapter.py`:
   - Input: a `polib.POEntry`. Output: a normalised
     `BlockInfo(block_type, source_ref, line_no)` where `block_type` ∈
     `{heading, list_item, paragraph, table_cell, code, attribute, unknown}`.
   - Parsers (each a small pure function, individually unit-tested):
     - **po4a:** `#. type:` extracted comments (`entry.comment`), e.g.
       `Plain text` → paragraph, `Title =`/`Title ##` → heading,
       `Bullet: '1. '` → list_item, `Fenced code block` → code.
     - **html2po (translate-toolkit):** element path embedded in the
       location (`entry.occurrences`), e.g. a path containing `.h1`–`.h6`
       → heading, `.li` → list_item, `.td`/`.th` → table_cell,
       standalone attribute entries (`alt`, `title`) → attribute.
     - Fallback: `unknown` (treated as paragraph downstream).
   - **Mode detection** `detect_document_po(po) -> bool`: true when a
     majority of entries have po4a `#. type:` comments OR html2po-style
     element-path occurrences clustered on one source file. Pure function,
     heavily unit-tested against fixtures.
2. **Test fixtures** under `tests/fixtures/document_po/`: one real
   po4a-generated PO from a small Markdown file, one html2po-generated PO
   from a small HTML file (generate once with the real tools, commit the
   outputs; note the generating command in a fixture README), plus a plain
   UI-string PO as negative case. Include entries with inline markup
   (links, `code`, bold) for later stages.
3. **Mode flag:** `translate.sh --mode <ui|document|auto>` (default `auto`)
   → `translate_runner.py --mode` → `po_translator.py`. In `auto`, run
   detection per file and **log which mode was chosen and why** (one line).
   Explicit flag always wins.
4. **Document-order processing** in `po_translator.translate_po_file()`
   when mode = document:
   - Load **all** entries (translated and not); sort by
     (source file, line) from `occurrences`, falling back to file order.
   - Skip `obsolete` entries; translate only untranslated/fuzzy entries,
     but keep translated neighbours in the ordered sequence (they become
     window context in Stage 3).
   - **No msgctxt grouping** in document mode (document POs effectively
     have none); batch consecutive entries up to `bulk_size`.
   - `attribute`-type entries are pulled out of the ordered flow and
     batched separately at the end (they are UI-like strings).
   - Payload items gain an optional `"type": <block_type>` field. The
     proxy must tolerate and ignore it in this stage (one-line change to
     `parse_input_payload` cleaning).
   - Plural expansion: document POs virtually never contain plurals; if a
     plural entry appears in document mode, expand it as today but log a
     notice.
5. **Docs:** `docs/12_document_mode.md` started: what document mode is, how
   to produce a compatible PO with po4a (`--wrap-po no` and `nowrap`
   options) and with html2po, the "translate the source layer, not
   rendered HTML" guidance, and round-trip testing advice.

### Acceptance criteria

- Unit tests: adapter parsers per extractor (parametrised over fixture
  entries); detection true/false/edge (empty file, mixed file); ordering
  (shuffled entry list → sorted correctly); attribute segregation; batching
  respects order and `bulk_size`.
- Dry-run integration: run `translate.sh --mode document` (dry-run model)
  on both fixtures; assert output PO has `[DRY RUN]` msgstrs for exactly
  the previously-untranslated entries, in place, with file structure and
  entry order preserved (byte-compare non-msgstr content).
- Human check: `--mode auto` on the demo UI-string PO prints "ui mode" and
  behaves exactly as before.

---

## Stage 3 — Contextual translation: rolling window, block conditioning, document prompts

**Goal:** The quality core. Consecutive entries are translated with a
rolling bilingual window and block-type-aware, document-specific prompts.

### Deliverables

1. **Payload contract v2** (additive). Document-mode batch items become:

   ```json
   {
     "text": "...",            // source msgid (unchanged)
     "context": "",            // unchanged (msgctxt; empty in doc mode)
     "type": "paragraph",      // from Stage 2
     "window": [                // only on the FIRST item of each batch
       {"src": "...", "tgt": "..."},   // up to N preceding entries
       {"src": "...", "tgt": null}     // tgt null if neighbour untranslated
     ]
   }
   ```

   - Window size `DOC_WINDOW_SIZE` env var, default 3. Window entries are
     the nearest preceding entries in document order, using their existing
     msgstr when available (from earlier batches in this run, or
     pre-existing translations in delta runs). Untranslated neighbours are
     included as source-only (`tgt: null`) so the model still sees flow.
   - Only the first item of a batch carries the window (the rest of the
     batch *is* the continuation); this bounds token cost.
2. **rag-proxy document mode** (`app.py`):
   - Mode signalled via URL path segment `doc_mode` (same mechanism as
     `lang_xx` / `skip_rag`; client sets base_url accordingly) so it also
     works for any OpenAI-compatible caller.
   - **Prompt resolution with mode dimension** in
     `get_system_prompt_from_md`: try `custom/{lang}.document.md` →
     `{lang}.document.md` → `document.generic.md` → existing UI chain.
     Ship a language-neutral `config/prompts/document.generic.md`:
     translate as continuous document, maintain established register and
     terminology from the provided preceding pairs, block-type rendering
     rules stated generically ("render headings as headings per
     target-language conventions"), preserve inline markup exactly.
   - **Prompt assembly:** window pairs rendered inside the [REFERENCE DATA]
     framing as a `<preceding_context>` section (read-only, like TM
     matches); per-item block types listed in the user-visible structure
     ("Item 3 is a heading"). Keep `_format_instruction` (count contract)
     unchanged.
   - **Failure isolation:** if a batch fails permanently, subsequent
     batches simply have fewer translated neighbours (tgt null) — verify no
     crash and no silent window misalignment.
3. **Custom document prompts** (user requirement): document the
   `custom/{lang}.document.md` override in `docs/12_document_mode.md` and
   README, mirroring the existing custom-prompt section.
4. **Logging:** log entry gains `"mode": "document"`, `"window_size"`, and
   per-item `"type"` so `analyse_logs.py` and humans can audit context.

### Acceptance criteria

- Unit tests: window construction (start of document, mid-run, untranslated
  neighbours, window spanning a failed batch); payload serialisation;
  proxy prompt-resolution chain incl. fallbacks (temp prompt dirs);
  prompt assembly contains window pairs inside reference framing and the
  correct item count.
- Integration (dry-run): full document-mode run over the po4a fixture;
  assert proxy log entries show mode=document, correct window contents for
  batch 2+ (built from batch 1's dry-run outputs).
- Human check (one small real API run, cheap model): translate the
  ~20-entry fixture into any language; verify the output reads as
  continuous prose and headings are not rendered as sentences. This is a
  judgement check — record observations in the PR description.

---

## Stage 4 — Inline markup protection + validation plugins

**Goal:** Structural safety for document content: markup survives
translation, and failures degrade to `fuzzy`, never silent corruption.

### Deliverables

1. **Masking module** `services/toolbox/src/markup_mask.py`:
   - `mask(text) -> (masked_text, token_map)` and
     `restore(translated, token_map) -> text | raises MarkupRestoreError`.
   - Masks (ordered, non-overlapping): fenced/inline code spans, Markdown
     links `[label](url)` (label stays translatable; URL masked), autolinks,
     HTML tags with attributes (tag + attrs masked as one token; inner text
     stays translatable), HTML entities, printf/brace placeholders
     (`%s`, `{name}`) — reuse pattern list style from existing post
     processors if present.
   - Placeholder format: `⟦T0⟧`, `⟦T1⟧`… (unlikely to be "translated";
     validate restoration is exact and complete — every token restored
     exactly once, no leftovers).
   - Applied in `po_translator` around each document-mode slot; on
     `MarkupRestoreError` after retries, keep msgstr empty (or prior
     value in delta runs) and add the `fuzzy` flag + a `#,` comment noting
     the failure. Window entries use the *unmasked* text.
2. **Validation post-process plugins** (existing framework,
   `services/toolbox/src/plugins/` + `post_process.py`), each an
   independent plugin, document-mode-aware but harmless in UI mode:
   - `markup_integrity`: re-scan output for orphan placeholders / broken
     link syntax / unbalanced HTML tags → flag fuzzy.
   - `untranslated_passthrough`: msgstr identical (case/space-normalised)
     to msgid for non-code block types → flag fuzzy. Must be skippable via
     config for language pairs where identity is legitimate.
   - `length_ratio`: msgstr/msgid char-length ratio outside configurable
     band (default 0.3–5.0, per existing `_is_suspicious_entry` spirit) →
     flag fuzzy.
   - Each plugin logs a one-line summary (entries checked / flagged).
3. **Docs:** validation + masking section in `docs/12_document_mode.md`
   and a note in `docs/2_post_processing.md`.

### Acceptance criteria

- Unit tests: mask/restore round-trips over a corpus of tricky strings
  (nested emphasis, link-in-list, code containing `[`/`]`, multiple
  identical tags, attribute entries); restoration failures raise; each
  plugin's flag/no-flag cases; fuzzy flag + comment written correctly via
  polib.
- Integration (dry-run): document fixture containing markup → output PO
  has all markup byte-identical inside `[DRY RUN]` msgstrs; deliberately
  corrupt a restore (test hook) → entry is fuzzy, run completes.
- Human check: run the real-API smoke from Stage 3 again; confirm links
  and code spans in the output are intact and clickable after `po2html` /
  po4a round-trip of the fixture.

---

## Stage 5 — Document-mode retrieval + cost estimation

**Goal:** Make RAG retrieval meaningful for paragraph-length text, and make
the pre-flight cost estimate honest for document mode (user requirement).

### Deliverables

1. **Lexical-first glossary matching in document mode** (rag-proxy):
   - For collections of kind `glossary`, when mode=document, match by
     scanning the entry text (plus its window source text) for glossary
     source terms using stemmed-token containment (reuse
     `snowballstemmer` / `has_shared_stems` machinery; build a
     stem-indexed term map per collection, cached with invalidation on
     collection change). Embedding query is the fallback when lexical
     matching yields nothing.
   - Note in code + docs: stemming is English-source-only (as already
     documented in `app.py`); non-English source falls back to exact
     token containment.
   - TM-kind collections keep embedding retrieval, but query text is the
     entry only (not entry+window) and results are labelled clearly.
   - `docs/3_RAG_performance_analysis.md` gains a section: UI-calibrated
     thresholds do not transfer to paragraph text; how to recalibrate per
     collection using the Stage-1 per-collection analyse flow.
2. **Cost estimation for document mode** (`estimate_cost.py`,
   `bin/translate.sh` pre-flight):
   - `--mode` flag mirroring the translator; document mode computes:
     source tokens (as today) + per-batch overhead where the RAG constant
     is replaced by: window overhead (window pairs ≈ 2 × mean entry length
     × `DOC_WINDOW_SIZE`, first item of each batch only), block-type
     annotation overhead (small constant per item), and the document
     prompt base (measure the shipped `document.generic.md` length; derive
     the constant the same way as the existing 375-token figure and
     document the derivation in `docs/9_cost_estimation.md`).
   - Must reuse the *same* Stage-2 ordering/filtering helpers as the
     translator so counts can't drift (same pattern as today's reuse of
     `_expand_entry`).
   - Keep the KEY=VALUE stdout contract; add `MODE=document`.
3. **`analyse_logs.py`:** handle document-mode logs (mode field, lexical
   glossary hits vs embedding hits distinguished so threshold stats aren't
   polluted by lexical matches).

### Acceptance criteria

- Unit tests: stem-index build + lookup (hit, miss, multi-word terms,
  case), fallback to embedding when no lexical hit (mocked collection);
  estimator arithmetic for document mode incl. window maths; estimator
  and translator agree on slot counts for all fixtures.
- Integration: dry-run document translation with a glossary collection
  containing terms present in the fixture → proxy log shows lexical
  glossary hits attached to the right entries.
- Human check: pre-flight estimate for the fixture in both modes; document
  mode shows higher per-batch overhead; sanity-check the numbers against
  one real run's `token_usage_*.json` (within ~2× band).

---

## Stage 6 — Document pre-pass summary (with cache)

**Goal:** One cheap up-front LLM call per document that yields a summary +
explicit style/register decision, injected into every subsequent batch.

### Deliverables

1. **Pre-pass step** in `po_translator` (document mode, real runs only;
   dry-run synthesises a placeholder summary):
   - Concatenate msgids in document order (cap at a configurable char
     budget, default ~24k chars, taking the head of the document).
   - One LLM call using a new language-neutral prompt
     `config/prompts/document.prepass.md`: return a compact JSON object
     `{summary, audience, register_decision, heading_style}` — the model
     states its decisions *in its own words for the target language*;
     nothing language-specific in the prompt.
   - Robust JSON extraction (reuse `_parse_translations`-style raw_decode
     scanning); on failure, log a warning and proceed without a pre-pass
     (never block the run).
2. **Cache:** sidecar file next to the input PO
   (`<name>.prepass.<lang>.json`) keyed by SHA-256 of (concatenated
   source + prompt file hash + model id). Reuse when the key matches;
   `--refresh-prepass` flag forces regeneration.
3. **Injection:** the pre-pass JSON is passed to the proxy in the payload
   (top-level optional field `"doc_brief"`) and rendered inside the
   [REFERENCE DATA] framing as `<document_brief>`. Cost estimator adds the
   pre-pass call (input ≈ concatenated source tokens) and per-batch brief
   overhead.

### Acceptance criteria

- Unit tests: cache key stability/invalidation (source change, prompt
  change, model change), JSON extraction failure path, char-budget
  truncation, dry-run placeholder.
- Integration (dry-run): brief present in every batch's proxy log entry.
- Human check: one real run; read the generated brief for reasonableness;
  re-run and confirm cache hit (no second pre-pass call in logs).

---

## Stage 7 (later, separate approval) — Running term record & delta staleness

Deliberately deferred; each item needs its own design pass before
implementation:

- **Running term record:** collect model-settled term renderings during a
  run; inject at *lower* priority than real glossaries; export as draft
  glossary CSV for human review. Risk: locking in early bad renderings —
  design must include review-before-reuse.
- **Delta staleness sidecar:** per-msgid-hash record of (model, prompt
  version, glossary versions) to mark entries stale when inputs change;
  `msgmerge`-based delta already covers the common case and is documented
  in `docs/12_document_mode.md` instead.

---

## Testing & workflow notes for the implementer

- Test harness: `bin/run_tests.sh` (pytest inside the toolbox container;
  `--run-integration` needs the stack up), `bin/run_bash_tests.sh` (bats).
  Every stage adds tests in the matching tier; integration tests must be
  skippable without the stack, following existing markers in
  `tests/pytest.ini` / `tests/conftest.py`.
- Dry-run is the default verification path; real-API smoke checks are
  explicitly listed per stage and should use the cheapest configured model.
- One PR (or reviewable unit) per stage; PR description lists which
  acceptance criteria were run and their results, including the human
  judgement checks.
- Keep `CHANGELOG.md` updated per stage; new user-facing flags go into
  README's flag table.
