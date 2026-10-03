# Plan: Document Mode (feature 3 of 3)

**Date:** 2026-10-01
**Decisions:** `document-translation-decisions.md`, section 3 and round 10.
Question numbers below refer to it. Where this plan and the log disagree,
the log wins; fix the plan.
**Prerequisites:** `source-language-awareness.md` and
`collections-presets.md` released. Does **not** depend on the
`tmgmt-integration` branch, which stays unmerged.

## Goal

Translate a long document (HTML, Markdown, plain text) with consistent
terminology. The user gives one file and gets the translated file back
with its markup intact; PO is an internal format only (Q3).

## Out of scope

- Other formats (Q43a). Add them later as new adapters.
- Selecting part of a page (`--selector`); the user prepares content-only
  input (Q2, Q8).
- `.po`/`.pot` input (Q43).
- Translating front matter (Q57); hierarchical briefs for oversized
  documents (Q50); caching the brief (Q19); explicit prompt-cache markers
  (Q54); a background job service (Q49).
- LLM-based quality checks; left to custom prompts (Q28).
- Re-translating an updated document from a previous version
  (`--previous-source` / `--previous-output`, Q61). Nice-to-have; v1 only
  keeps extraction deterministic so it can be added later.

## Architecture (Q51)

- **Toolbox** orchestrates: conversion, chunking, brief, window, term
  record, final pass, validation, report, resume, queue.
- **rag-proxy** does retrieval and prompt assembly. The payload envelope
  from feature 1 gains optional fields: `mode: "document"`, `brief`,
  `window`, `record_terms`, and a per-item `type`. Requests without them
  behave as today.
- The brief and final-pass calls need no retrieval: they go straight to
  LiteLLM via `LLM_BASE_URL`, as `evaluate_blind_test.py` does for the
  judge.
- The core is a Python function, `translate_document(...)`, that the CLI
  wraps and that TMGMT can call later (Q14).

## Milestones

Each milestone ends with green tests and a dry-run on the fixtures.

### M0. Dependency and round-trip spike

- Add `translate-toolkit[markdown]` (3.20.0 checked; pin it) to the
  toolbox requirements, in the same single `pip --target` resolution as
  the rest. Rebuild.
- **Unverified so far:** round-trips. For each fixture: extract → PO →
  fill msgstr with msgid → rebuild, and diff against the input. Note every
  difference (whitespace, entity encoding, attribute order). If a
  difference changes meaning or breaks rendering, stop and raise it.

### M1. Format adapters and CLI (Q7, Q43, Q44, Q56, Q57)

- `services/toolbox/src/doc_formats/`: an adapter interface with
  `extract(path) -> PO units` (each unit carries its block type: heading,
  list item, table cell, paragraph, attribute) and `rebuild(po, path)`.
- **HTML:** subclass translate-toolkit's HTML parser. Excluded elements
  (`pre`, `code` blocks, `script`, `style`) and translatable attributes
  (`alt`, `title`, `aria-label`, `placeholder` …) come from config. Add a
  guard test that fails if the upstream class-level lists it overrides
  change. Pin translate-toolkit.
- **Markdown:** `md2po` with `--no-code-blocks`; front matter kept
  verbatim and noted in the report; inline HTML stays as `{n}`
  placeholders.
- **Plain text:** `txt2po`, paragraph per blank-line block.
- **CLI:** `bin/translate_doc.sh --source-lang en --target-lang ja
  [--preset X] [--format F] [--output P] [-y] [--resume] file|dir|list`.
  Format from the extension unless `--format`; unknown extensions are
  rejected; output `page.md` → `page.ja.md`. One target language per run.

### M2. Chunking, window and prompts (Q5, Q9, Q10, Q12, Q18, Q54, Q62)

- Units stay whole: never split below paragraph level.
- Batches by token budget (default ~250 source tokens, configurable;
  0 = one unit per call). Only short units (headings, list items, table
  cells) are grouped; a paragraph never shares a call with another
  paragraph; a long paragraph goes alone.
- Attribute values are batched separately and use `match.ui` retrieval
  (Q44).
- Window: the 3 preceding source+target pairs (configurable), independent
  of batch boundaries. A paragraph that failed and kept its source goes in
  with no target (`tgt: null`), never with its source as the target (Q62).
- Prompt chain `custom/{lang}.document.md` → `{lang}.document.md` →
  `document.generic.md`; ship the generic one. Static parts first (system
  prompt, brief, instructions), then window, retrieval hits and items.
  Leave a TODO comment to revisit explicit prompt caching after the
  benchmark (Q54).

### M3. Brief (Q4, Q11, Q50)

- One call per document before translation: summary, audience, register,
  key terms. Summary in the source language; key terms and register also
  in the target language.
- `BRIEF_MODEL` setting, defaulting to the translation model. Its context
  window comes from model config (`config/models/models.yaml`). If the
  source exceeds the window minus a margin, stop with an error naming
  both token counts.
- The brief is sent with every batch (`brief` field).

### M4. Retrieval in the proxy (Q13, Q15, Q22, Q64)

Implements `match.document` from feature 2:

- **`lexical`** (glossary): return all terms present in the paragraph,
  using `core.text` words and stems. Overlaps resolve leftmost-longest,
  per occurrence (a short term is kept if it also appears standalone).
  No cap; deduplicate per batch.
- **`phrase`** (TM): normalised phrase containment, longest match, at
  least 2 words, stop-list from config, framed as "use if applicable".
- **`fuzzy`** (TM): split the paragraph into sentences (`core.text`);
  per sentence, get ~10 embedding candidates, re-rank by word-level edit
  distance (character-level for CJK), keep those above the threshold
  (~70–75 %, configurable). Separate thresholds for `phrase` and `fuzzy`.
- Every hit is logged with its collection and matcher.
- `analyse_logs.py` reports hits per matcher and bases distance-threshold
  recommendations on embedding (`match.ui`) hits only (Q64).

### M5. Consistency (Q29–Q33, Q38, Q38a, Q46)

- **Response format** in document mode: `{"translations": [...], "terms":
  [{"src", "tgt"}]}`. The proxy's format instruction gets a document
  variant; the toolbox parser keeps the count contract.
- **Term record:** collected from `terms`. Only recorded terms that occur
  in the current paragraph are sent (`record_terms`), using the same
  lexical matcher. A glossary hit always overrides a recorded term.
- **Final pass:** find source terms with more than one rendering (string
  comparison, no LLM). Canonical rendering = the glossary's, else the most
  frequent. Re-edit only the affected paragraphs: mark the span, give the
  required rendering, "change nothing else". Accept only if the diff
  touches only that span and the markup check passes. No flagged terms →
  no calls.
- **Draft glossary:** export the record to
  `data/term_drafts/<preset>.<src>-<tgt>.csv` (no preset →
  `adhoc_<sorted collection names>.<src>-<tgt>.csv`). Skip terms already
  in the preset's collections or the draft. Same term with a different
  rendering → keep both and mark the conflict in the file and in the
  end-of-run summary.

### M6. Validation, failure and report (Q17, Q28, Q37, Q45, Q63)

- **Markup check:** same tag set and attributes (HTML), same placeholder
  set (Markdown `{n}`).
- **Omission check:** target/source length ratio against the document's
  own median, with median absolute deviation, above a minimum length. Use
  a wide default band from `config/languages.yml` until enough paragraphs
  exist, or a TM-derived ratio when a TM exists.
- **Echo check:** output equal to the source (whitespace- and
  case-normalised) is flagged, except for code and below the omission
  check's minimum length (Q63).
- **Failure:** markup mismatch, omission or echo flag, or no usable response
  (API error after retries, unparseable, wrong count). Retry once, then
  keep the source paragraph.
- **Report** `<name>.<lang>.report.md`: failed paragraphs (reason,
  source, rejected output), final-pass edits, term conflicts, front-matter
  note. One-line summary at the end of the run.

### M7. Operations (Q47, Q48, Q49)

- **Cost estimate:** a range covering the brief, the batches (window,
  brief and retrieval overhead) and the final pass at its worst case.
  Confirmation prompt; `-y` skips it. Reuse the same chunking code as the
  translator so counts can't drift.
- **Dry run** (`dry-run-dummy`): placeholder brief, `[DRY RUN] <source>`
  output, no model terms but a test hook injects some, the final pass runs
  on the planted terms, the omission check is skipped, the report is
  still produced.
- **Resume:** checkpoint after every call (the work PO plus a state file
  holding brief, window and term record); `--resume` continues.
- **Queue:** directory or list input; documents run concurrently up to a
  configurable limit; paragraphs within a document stay sequential.

## Tests

- **Fixtures:** `tests/fixtures/documents/`. Small hand-made HTML,
  Markdown and text files covering inline markup, `<pre>`/code blocks,
  translatable attributes, tables, front matter, and a long paragraph.
  Plus the benchmark page (below). A README notes sources and licences.
- **Unit:** adapters and the upstream guard test; batching rules; window
  across batch boundaries; brief size check; each matcher (overlaps, stop
  words, CJK edit distance); response parsing; term-record filtering and
  glossary precedence; final-pass detection, canonical choice and diff
  check; markup and omission checks; report contents; estimator agrees
  with the translator's chunking; resume from a checkpoint.
- **Bats:** `translate_doc.sh` flags, output naming, unknown extension,
  `-y`, `--resume`.
- **Integration (dry-run, scratch stack):** each fixture end to end.
  Markup round-trips, planted terms reach the final pass, the report is
  produced.

## Acceptance (Q52, Q53)

1. **Merge gate:** all dry-run fixtures pass as above; full suite green.
2. **Benchmark:** run by hand with a real model; **ask before each run**,
   since it costs money. Source: Drupal User Guide "Concept: Content
   Entities and Fields"
   (<https://www.drupal.org/docs/user_guide/en/planning-data-types.html>),
   reference
   (<https://www.drupal.org/ja/docs/user_guide/ja/planning-data-types.html>).
   CC BY-SA 2.0; keep attribution, including the Japanese translators.
   The Japanese page is labelled "Drupal 8"; check it matches the current
   English text before scoring, and trim to the aligned parts if not.
   Metrics: chrF and term consistency; COMET optional; no LLM judge.
   Record the results in the PR description.

## Docs and changelog

- `CHANGELOG.md` `[Unreleased]`, one entry per user-visible addition
  (document translation command, each format, term drafts, report,
  resume, queue).
- New `docs/12_document_translation.md` (`10_` is claimed by
  `tmgmt-integration`, `11_` by collections): usage, formats and their
  limits, what is never translated, custom document prompts, the report,
  term drafts, cost. README flag table.
- `docs/9_cost_estimation.md`: document-mode estimate.
