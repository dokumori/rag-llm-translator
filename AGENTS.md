# Agent instructions

Drupal .po translation pipeline with RAG. Services (docker-compose):
`rag-proxy` (Flask, OpenAI-compatible proxy that injects Chroma context),
`toolbox` (CLI scripts: translate, evaluate, ingest), `litellm`, `chroma`.
Shared Python code lives in `services/shared/src/core/`.

## Commands
- Rebuild after any `requirements.txt` or Dockerfile change:
  `docker compose up -d --build` (plain `up -d` reuses stale images).
- Tests run inside the toolbox container, never on the host:
  - `bin/run_tests.sh` (unit), `bin/run_tests.sh --run-integration` (stack must be up)
  - `bin/run_bash_tests.sh` (shell scripts)

## Non-obvious facts
- Python deps are installed with `pip --target` into `/dependencies` and
  exposed via `PYTHONPATH`, not site-packages. Anything that overrides
  `PYTHONPATH` (docker-compose.yml, bin/run_tests.sh) must keep `/dependencies`.
- The tests mock the OpenAI client and the embedding model. A green suite
  does not prove an SDK, torch or sentence-transformers change is safe:
  also exercise the real library.
- Changing the embedding model means reindexing Chroma. For an upgrade of
  its libraries (sentence-transformers, transformers, torch), first re-embed
  the stored documents and compare against the vectors already in Chroma;
  reindex only if they differ.
- Renovate PRs have no CI. "Mergeable" only means no textual conflict.

## Safety
- LLM calls cost money. Use the `dry-run-dummy` model for testing, and ask
  before making real provider calls.
- Never print, log or commit values from `.env`.
- Ask before destructive actions against the main stack or `data/`
  (e.g. `docker compose down -v`, deleting translations or collections).

## Git
- Commit messages: Conventional Commits, `type(scope): subject`
  (e.g. `fix(docker): …`, `docs(changelog): …`).
- User-visible changes get an entry under `## [Unreleased]` in CHANGELOG.md,
  one change per entry, so each can be reverted independently.

## Code
- Keep changes scoped to the task. Don't delete or rewrite unrelated code
  or comments; if you remove something, say what and why.
- Comments explain *why* (intent, constraints, gotchas), not what the code does.
- Errors: catch specific exceptions where you can recover (retry, fallback,
  clear message). Otherwise log with context and re-raise or exit non-zero.
  Never `except Exception: pass`.
- Use `logging` for operational output; `print()` only for CLI output.
- No hard-coded URLs, model IDs, paths or limits: use `core.config.Config`,
  `.env`, or `config/*.yaml`, and reuse existing constants.
- Type hints on every new or changed function signature.
- British English in identifiers, comments, docs and the changelog.
- Python: PEP 8. Bash: `#!/bin/bash`, Google Shell Style Guide.

## Before saying "done"
- Run the relevant tests and quote failures verbatim.
- State what you did *not* verify.
