# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
