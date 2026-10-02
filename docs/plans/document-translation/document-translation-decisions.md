# Decision Log: Document Translation Feature

**Started:** 2026-10-01 (grilling session, round 1–9)
**Status:** Design agreed (round 10). Plans written: `source-language-awareness.md`, `collections-presets.md`, `document-mode.md`
**Supersedes:** parts of `document-mode-implementation-plan.md` (2026-07-22
draft). Where the two disagree, this log wins. The draft remains the
reference for anything this log does not cover.

## Goal

Translate long text (multi-paragraph documents: user documentation, blog
posts) with the RAG-LLM Translator, keeping terminology consistent. The
translator was built for short UI strings; this extends it to long text.
Internally the pipeline stays gettext-based (PO is an intermediate format
only — the user never sees it). Future TMGMT integration will *use* this
feature; it does not depend on the `tmgmt-integration` branch, which stays
unmerged.

## Delivery order (Q39)

Three separate features, each shipped and verified on its own:

1. **Source-language awareness** — stop assuming English is the source.
2. **Collections and presets** — optional, user-defined collections.
3. **Document mode** — the feature itself.

---

## 1. Source-language awareness

| # | Decision |
|---|---|
| Q34 | v1 defaults to the current English embedding model. Switching models is already supported (`bin/switch-embedding-model.sh`); it requires re-ingesting everything. |
| Q40 | Scope: (1) prompts — "from English" → "from `{source_lang}`" (`config/prompts/generic.md:2`); (2) proxy matching — stemmer, stop-words, guardrail per source language (`app.py:17`, `app.py:220`); (3) ingestion — `source_langcode` metadata, backfill existing entries with `en`; (4) cost estimator — chars-per-token per language (`estimate_cost.py:72`). Glossary extraction from the Drupal DB is out of scope (Drupal msgids are always English). |
| Q36 | Text processing: **ICU (PyICU) + Snowball**, one engine with per-language data in config (stop-lists, abbreviations, ratio bands). No per-language code paths. Snowball where the language is supported, exact matching otherwise. ICU covers CJK/Thai word and sentence segmentation. **To verify:** PyICU builds on the Python 3.14 image. |
| Q41 | Source language comes from an explicit `--source-lang` flag, default `en`. No auto-detection. |
| Q42 | Declare supported languages per embedding model in config; warn (not block) when the source language isn't covered. Unknown → say "unknown". |
| Q40a | Collections may mix **any combination of source and target languages**. Both are per-entry metadata; lookups filter on both. Warn at ingestion when an entry's source language isn't covered by the collection's embedding model. Proposed entry shape (user's sketch): `{"source_original": "Authored on", "source_langcode": "en", "target": "作成日", "target_langcode": "ja", "context": ""}` — field names to be finalised (today: `langcode`, `msgctxt`/`context`). |

Acceptance: English-source output identical to today's.

## 2. Collections and presets (plan's Stage 1, revised)

| # | Decision |
|---|---|
| Q20 | Separate feature, shipped before document mode. Useful for UI translation too. |
| Q21 | **No fixed kinds.** Each collection is configured freely. `glossary` and `tm` ship as built-in defaults that reproduce today's behaviour. |
| Q24 | New collections inherit via `base: glossary` / `base: tm` and override individual settings. Later: set these via command options or an interactive flow like `initial_setup.sh`. |
| Q25 | User-facing settings: `base`, `source_format` (csv \| po), `match.ui`, `match.document`, `threshold`, `format` (named choices only: `term_list`, `pairs` — no free templates, to protect the reference-data framing). Guardrail is always on for embedding matching (not a setting). `context_key` stays as today for UI mode; not used in document mode. |
| Q26 | Prompt sections grouped by `format`: all `term_list` hits under `<glossary_matches>`, all `pairs` hits under `<tm_matches>`. Existing prompts keep working. Logs record the source collection per hit. |
| Q27 | Conflicts between collections: show all renderings in preset order, first marked **preferred**; prompt rule: use the preferred one unless context clearly calls for another listed sense. Log every conflict. |
| Q23 | Registry in `config/rag/collections.yml` (git-ignored, committed `.example`). `--preset <name>` or `--collections a,b`; neither → `default` preset, **no prompt**. Built-in `none` preset = no lookup. Missing file → synthesise default from `TM_COLLECTION` / `GLOSSARY_COLLECTION` env vars. |

## 3. Document mode

### Input, output, invocation

| # | Decision |
|---|---|
| Q2/Q8 | Input is one local file. The whole file is translated; the user prepares content-only input. A `--selector` for HTML may come later. |
| Q3 | Output is the translated document with markup restored; PO is internal only. |
| Q43 | `bin/translate_doc.sh --source-lang en --target-lang ja [--preset X] file`. Format from extension, kept in output (`page.md` → `page.ja.md`); `--format` overrides; unknown extensions rejected; `--output` overrides path. One target language per run. Formats: **HTML, Markdown, plain text** at minimum. `.po`/`.pot` deliberately excluded. Core written as a Python function TMGMT can call later (Q14). |
| Q7 | Conversion via translate-toolkit (`html2po`/`po2html`, `txt2po`/`po2txt`, Markdown converter). New dependency → image rebuild. **To verify:** Markdown converter exists; what `html2po` extracts by default (code blocks, attributes). |
| Q44 | Never translated: `<pre>`, `<code>`, `<script>`, `<style>` content; tag names; attribute names; non-human-readable attribute values (`href`, `src`, `class`, `id`, `data-*`…). Translated: human-readable attribute values — `alt`, `title`, `aria-label`, `placeholder` (configurable list) — e.g. `alt="Penguin"` → `alt="ペンギン"`, never `alt` → `代替`. Attribute values use `match.ui`. |

### Chunking and context

| # | Decision |
|---|---|
| Q5/Q10 | Chunks follow paragraph boundaries, never character counts. No splitting below paragraph level. |
| Q9 | **Token budget per call (~250 source tokens):** consecutive short items (headings, list items) grouped; a paragraph never shares a call with another paragraph (only short items are grouped); a long paragraph goes alone. Plus **3 preceding source+target pairs** as a window, independent of batch boundaries. Both configurable; budget 0 = one item per call. |
| Q4 | **One up-front brief** of the whole text, no rolling summary (cost). |
| Q11 | Brief = summary, audience, register, key terms; summary in source language, key terms and register also stated **in the target language** (bilingual — DelTA evidence). |
| Q12 | Previous context given as source+target pairs. |
| Q19 | Brief not cached in v1. |
| Q18 | Document prompt chain: `custom/{lang}.document.md` → `{lang}.document.md` → `document.generic.md` (ship the generic one). |

### Retrieval

| # | Decision |
|---|---|
| Q13 | Glossary for paragraphs: **lexical matching** returning all terms present (today: `n_results: 1`, `app.py:288`). |
| Q15 | Overlaps: leftmost-longest, removed **per occurrence** (short term kept if it also appears standalone). **No cap** on hits. Deduplicate per batch. |
| Q22 | TM for paragraphs: `match.document` supports **phrase containment** (normalised, longest match, min 2 words, stop-list, "use if applicable" framing) and **per-sentence fuzzy matching** (embedding top-k candidates via `n_results` ≈ 10, re-ranked by word-level edit distance, ~70–75 %; char-level for CJK). Combinable, separate thresholds. |

### Consistency

| # | Decision |
|---|---|
| Q29 | Running **term record** in v1. |
| Q31 | Model reports terms in the same response: `{"translations": [...], "terms": [{"src", "tgt"}]}` (document mode only; parser keeps the count contract). |
| Q32 | Record ranks **below** glossary; glossary hit always overrides. |
| Q46 | Inject only recorded terms that appear in the current paragraph (same lexical matcher). |
| Q30 | **Targeted final pass:** find source terms with >1 rendering (string comparison, no LLM); canonical = glossary's, else most frequent; re-edit only affected paragraphs with marked span + required rendering, "change nothing else"; validate with diff (only the span changed) + markup check. Zero cost when nothing is flagged. |
| Q33/Q38 | Record exported as a draft glossary CSV: `data/term_drafts/<preset>.<src>-<tgt>.csv`; no preset → `adhoc_<sorted collection names>.<src>-<tgt>.csv`. Skip terms already in the preset's collections or the draft; same term with a different rendering → keep both, mark conflict. |
| Q38a | Conflicts marked in the file **and** summarised at end of run (may be suppressed later). |

### Validation and failure

| # | Decision |
|---|---|
| Q17 | Inline markup stays visible to the model; after translation verify same tag set and attributes. |
| Q28/Q37 | Omission check: compare against the **document's own median target/source ratio** (median absolute deviation), applied above a minimum length; wide default band until enough paragraphs; TM-derived ratio when a TM exists. LLM-based checks are left to custom prompts. |
| Q45 | A paragraph "fails" on markup mismatch, omission flag, or no usable response (API error after retries, unparseable, wrong count). Retry once → keep source paragraph → list in `<name>.<lang>.report.md` (reason, source, rejected output) + one-line end-of-run summary. The report also lists final-pass edits and term conflicts. |

### Operations

| # | Decision |
|---|---|
| Q47 | Pre-flight cost estimate as a **range** (final pass is worst-case), confirmation prompt, `-y` to skip. |
| Q48 | Dry run: placeholder brief; `[DRY RUN] <source>`; no model terms, test hook injects some; final pass runs on planted terms; omission check skipped; report still produced. |
| Q49 | **Resumable runs** (checkpoint after every call; intermediate PO already records progress; `--resume`) **+ multi-document queue** (directory/list input; documents concurrently, configurable limit). Paragraphs within one document stay sequential (window + term record). Background job service out of scope (belongs with TMGMT). |

---

## Round 10 (2026-10-01, second session)

| # | Decision |
|---|---|
| Q50 | Brief: **one call when the source fits** the brief model's context window with margin (window from model config); separate `BRIEF_MODEL` setting, defaulting to the translation model. v1: source too large → clear error naming token count and window. Hierarchical fallback later. Brief cost is its own line in the pre-flight estimate. |
| Q43a | v1 formats: **HTML, Markdown, plain text** only, behind a converter-adapter interface (`extract → PO`, `PO → rebuild`). Other formats not discussed until needed. |
| Q51 | Keep the July draft's split: toolbox orchestrates (conversion, chunking, brief, window, term record, final pass, report); rag-proxy does retrieval and prompt assembly. Payload extended with optional fields only. |
| Q52 | Feature 3 acceptance: (a) dry-run fixtures pass (markup round-trip, report produced) as the merge gate, **and** (b) a real-model benchmark run on a reference document (manual, cost approved per run). |
| Q53 | Benchmark document: Drupal User Guide "Concept: Content Entities and Fields" — EN <https://www.drupal.org/docs/user_guide/en/planning-data-types.html>, JA reference <https://www.drupal.org/ja/docs/user_guide/ja/planning-data-types.html>. CC BY-SA 2.0; fixture carries attribution (incl. JA translators). Metrics: chrF + term consistency, COMET optional, no LLM judge. Note: JA page is titled "Drupal 8 ユーザーガイド" — may lag the current EN text; check alignment when building the fixture. |
| Q54 | Prompt caching: order prompts static-first (system, brief, instructions) so automatic provider caching can apply; no cache markers. Leave a TODO comment to revisit explicit caching after the benchmark. |
| Q55 | Three new plans (`source-language-awareness.md`, `collections-presets.md`, `document-mode.md`); July draft kept with a "superseded" header. |
| Q57 | Markdown: always `--no-code-blocks`; front matter kept verbatim (noted in report); inline HTML stays as `{n}` placeholders, covered by the markup check. |
| Q40a | Entry metadata unified: `{"source_langcode", "target_langcode", "target", "context"}` (+ `file` for TM). Source text stays the Chroma document. `langcode` → `target_langcode`; TM `msgctxt` → `context`; `source_original` (duplicate of the document, unused) dropped; `context_key` setting removed from Q25. Existing collections are re-ingested (Q60). |
| Q59 | Entry ID hash includes the source language. |
| Q60 | **No migration.** Feature 1 ships as a breaking change (7.0.0): CHANGELOG states "re-ingest required" with steps (`--reset`). The proxy checks one record per collection at startup; old-format collection → clear error naming the re-ingest command, lookups on it refused (no silent empty results). Ingest API renames `langcode` → `target_langcode` outright, no alias. Supersedes the "migrated in place" part of Q40a. |
| Q58 | PyICU compiled at image build is accepted (checked: PyICU 2.16.2 builds and splits Japanese correctly on amd64 under QEMU and arm64; compile ~100 s / ~52 s; builder needs `libicu-dev pkg-config g++`, runtime `libicu72`). Must work on **arm64 and amd64**. PyICU installed in its own cached build step, without a second `pip --target` into `/dependencies` (see pip re-resolve gotcha). |
| Q58a | ICU pinning: install `libicu72` by name (bookworm keeps upstream ICU at 72.1; only Debian patches change), `PyICU==2.16.2`, base image pinned by digest; tests with expected word/sentence splits catch behaviour drift. No exact Debian version pin (old versions are removed) and no ICU build from source. ICU is not semver: every regular release bumps the major. |
| Q56 | HTML adapter **subclasses the `html2po` parser**: excluded elements and translatable attributes from config; translate-toolkit pinned; guard test fails if upstream class lists change. |

## Open questions

None open as of round 10. Q50, Q43a, Q40a and the topics not yet visited in
round 9 (acceptance criteria, prompt caching, docs/changelog, the July draft)
are settled in the "Round 10" table above. Awaiting the user's confirmation
of a shared understanding before writing the three feature plans (Q55).

### Facts checked

Throwaway containers on the pinned `python:3.14-slim-bookworm` image,
2026-10-01. PyICU on amd64 and the `pip --target` install were checked
later (see Q58).

   - PyICU 2.16.2: no wheel; builds from sdist against ICU 72.1. Builder
     needs `libicu-dev pkg-config g++`; final stage needs `libicu72`.
   - translate-toolkit 3.20.0 supports Python 3.14. `md2po`/`po2md`
     (mistletoe, `[markdown]` extra): fenced code extracted unless
     `--no-code-blocks`; front matter extracted as one raw YAML string
     unless `--no-frontmatter`; table cells become separate units; inline
     HTML becomes placeholders `{1}…{2}`, emphasis/inline code stay as
     Markdown syntax.
   - `html2po`: extracts `<pre>` (conflicts with Q44); skips
     `<script>`/`<style>`; inline `<code>` and other inline tags stay as raw
     tags in the msgid. Attributes: `abbr, alt, lang` (`<html>` only),
     `summary, title, value`, meta description/og/twitter — **not**
     `placeholder`, `aria-label`. No CLI option; changing the lists means
     subclassing the parser. `<!-- translate:off -->` is supported.
   - Other converters: `asciidoc2po` (works; `= Title` line not extracted),
     `sub2po` for SRT (needs `aeidon`; `.vtt` rejected), `odf2po`/
     `odf2xliff` for ODT, `idml2po`. No converter for DOCX or rST.
   - snowballstemmer 3.1.1: 36 algorithms, no Chinese/Japanese/Korean.
   - Not verified: round-trips (`po2md`, `po2html`).

### Still unverified

- Round-trips back to the source format (`po2md`, `po2html`) — first task
  of feature 3.
- Whether the JA User Guide page matches the current EN text (Q53).

## Research notes

Literature searches run on 2026-10-01 (most sources read as abstracts
only):

- Paragraph/multi-sentence units beat sentence-level: Wang et al. 2023
  (EMNLP, arXiv:2304.02210); Karpinska & Iyyer 2023 (WMT, arXiv:2304.03245).
- Large windows cause omissions; summaries and proper-noun records drive
  consistency more than raw context: DelTA (ICLR 2025, arXiv:2410.08143).
- Pre-translation research + ~250-token chunks: Briakou et al. 2024
  (arXiv:2409.06790). Guidelines incl. summary/tone/audience: TransAgents
  (TACL, arXiv:2405.11804).
- Exact dictionary hints, lemmatisation made little difference: DiPMT
  (arXiv:2302.07856). Fuzzy TM few-shot, diminishing returns ~5: Moslem
  et al. 2023 (EAMT, arXiv:2301.13294). Token fuzzy beat embeddings:
  Rios Gaona et al. 2026 (EAMT).
- Targeted repair of inconsistent terms: Zhang et al. 2023 (ACL Findings);
  marked-span LLM post-editing: Berger et al. 2024 (EAMT). Unconstrained
  LLM post-editing can hallucinate: Raunak et al. 2023 (arXiv:2305.14878).
- No study compares running term record vs final pass vs both.
