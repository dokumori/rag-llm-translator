# Document Translation Plans

Plans for translating long text (HTML, Markdown, plain text documents)
with the RAG-LLM Translator, keeping terminology consistent. Delivered as
three features, in order; each is shipped and verified before the next
starts.

| Order | Plan | Release | Status |
|---|---|---|---|
| 1 | [Source-language awareness](source-language-awareness.md) | 7.0.0 (breaking: re-ingest) | Not started |
| 2 | [Collections and presets](collections-presets.md) | additive | Not started |
| 3 | [Document mode](document-mode.md) | additive | Not started |

Start with plan 1, task 1 (PyICU in both images): it decides whether the
rest of plan 1 is viable.

## Other files

- [Decision log](document-translation-decisions.md): every design decision
  (Q-numbers) and why it was made. The plans cite it; where a plan and the
  log disagree, the log wins and the plan gets fixed.

## Keeping this up to date

- Update the status column when a feature starts and when it's released.
- If implementation shows a plan was wrong, change the plan and the
  decision log in the same feature branch as the code.
