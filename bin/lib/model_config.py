"""
bin/lib/model_config.py
-----------------------
Shared Python module for model configuration logic used by shell scripts.

Provides two pure functions:
  - load_merged_models()    : merge base + custom models.json files
  - generate_custom_models(): build a models.json from provider selections

Can also be invoked as a CLI script by shell scripts:
  python3 bin/lib/model_config.py list   --base <path> [--custom <path>] --format names|json|lookup [--name <name>]
  python3 bin/lib/model_config.py generate --example <path> --output <path> --providers <str> [options]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def load_merged_models(base_path: str, custom_path: str | None = None) -> list[dict]:
    """
    Load and merge model configuration from base and optional custom JSON files.

    Behaviour:
    - If custom_path is provided and the file exists:
        - Use custom models (non-dry-run) + dry-run from custom (or base as fallback).
    - Otherwise:
        - Use base models, with any dry-run model moved to the end.
    - For all results: append " (dry run)" to the name of any dry-run model
      that does not already contain "(dry run)" (case-insensitive).

    Returns a list of model dicts.
    Raises FileNotFoundError if base_path does not exist.
    """
    base_models: list[dict] = json.loads(Path(base_path).read_text()).get("models", [])

    if custom_path and Path(custom_path).exists():
        custom_models: list[dict] = json.loads(Path(custom_path).read_text()).get("models", [])

        # Prefer dry-run from custom; fall back to base
        dry_run = next(
            (m for m in custom_models if m.get("is_dry_run")),
            next((m for m in base_models if m.get("is_dry_run")), None),
        )

        # Non-dry-run models from custom + the resolved dry-run at the end
        models = [m for m in custom_models if not m.get("is_dry_run")]
        if dry_run:
            models.append(dry_run)
    else:
        # Base only: move any dry-run model to the end
        models = (
            [m for m in base_models if not m.get("is_dry_run")]
            + [m for m in base_models if m.get("is_dry_run")]
        )

    # Ensure dry-run name has the "(dry run)" suffix
    for m in models:
        if m.get("is_dry_run") and "(dry run)" not in m.get("name", "").lower():
            m["name"] = f"{m['name']} (dry run)"

    return models


def generate_custom_models(
    example_path: str,
    providers: list[str],
    custom_names: list[str] | None = None,
    custom_displays: list[str] | None = None,
    ollama_models: list[str] | None = None,
) -> dict:
    """
    Build a models.json dict from provider selections and optional custom/Ollama entries.

    Behaviour:
    - Filter the example models by provider prefix mapping.
    - Append custom OpenAI-compatible endpoint entries (if "custom" in providers).
    - Append Ollama entries (if "ollama" in providers).
    - Always include the dry-run model from the example (if present).

    Returns {"models": [...]}.
    Does NOT write to disk — the caller is responsible for that.
    """
    prefixes: dict[str, list[str]] = {
        "anthropic": ["claude-"],
        "google":    ["gemini-"],
        "openai":    ["gpt-", "o3-", "o4-"],
        "mistral":   ["mistral-"],
    }

    example: dict = json.loads(Path(example_path).read_text())
    example_models: list[dict] = example.get("models", [])

    selected: list[dict] = []

    # Include example models that match any selected provider's prefixes
    for m in example_models:
        mid = m.get("id", "")
        for p in providers:
            if any(mid.startswith(pfx) for pfx in prefixes.get(p, [])):
                selected.append(m)
                break

    # Custom OpenAI-compatible endpoint entries
    if "custom" in providers and custom_names:
        displays = custom_displays or []
        for i, name in enumerate(custom_names):
            if name:
                display = displays[i] if i < len(displays) else name
                selected.append({
                    "id": name,
                    "name": display or name,
                    "is_dry_run": False,
                })

    # Ollama model entries
    if "ollama" in providers and ollama_models:
        for raw in ollama_models:
            model = raw.strip()
            if model:
                selected.append({
                    "id": model,
                    "name": f"Ollama \u2014 {model}",
                    "is_dry_run": False,
                })

    # Always include the dry-run model from the example (if present and not already added)
    dry_run = next((m for m in example_models if m.get("is_dry_run")), None)
    if dry_run and dry_run not in selected:
        selected.append(dry_run)

    return {"models": selected}


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def _cmd_list(args: argparse.Namespace) -> None:
    models = load_merged_models(args.base, getattr(args, "custom", None))

    if args.format == "names":
        for m in models:
            print(m["name"])

    elif args.format == "json":
        for m in models:
            print(json.dumps(m))

    elif args.format == "lookup":
        if not args.name:
            print("error: --name is required for --format lookup", file=sys.stderr)
            sys.exit(1)
        match = next((m for m in models if m["name"] == args.name), None)
        if match is None:
            print(f"error: model not found: {args.name!r}", file=sys.stderr)
            sys.exit(1)
        print(match["id"])
        print(str(match["is_dry_run"]).lower())

    else:
        print(f"error: unknown format: {args.format!r}", file=sys.stderr)
        sys.exit(1)


def _cmd_generate(args: argparse.Namespace) -> None:
    providers = args.providers.split() if args.providers else []
    custom_names = [n for n in args.custom_names.split("|") if n] if args.custom_names else None
    custom_displays = [d for d in args.custom_displays.split("|") if d] if args.custom_displays else None
    ollama_models = [m for m in args.ollama_models.split(",") if m.strip()] if args.ollama_models else None

    result = generate_custom_models(
        example_path=args.example,
        providers=providers,
        custom_names=custom_names,
        custom_displays=custom_displays,
        ollama_models=ollama_models,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="model_config",
        description="Model configuration utilities for the RAG-LLM Translator.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # -- list subcommand --
    list_p = sub.add_parser("list", help="List models from config files.")
    list_p.add_argument("--base", required=True, help="Path to the base models.json")
    list_p.add_argument("--custom", default=None, help="Path to the custom models.json override (optional)")
    list_p.add_argument(
        "--format",
        required=True,
        choices=["names", "json", "lookup"],
        help="Output format: names | json | lookup",
    )
    list_p.add_argument("--name", default=None, help="Model name to look up (required for --format lookup)")

    # -- generate subcommand --
    gen_p = sub.add_parser("generate", help="Generate a custom models.json from provider selections.")
    gen_p.add_argument("--example", required=True, help="Path to the models.example.json source")
    gen_p.add_argument("--output", required=True, help="Path to write the generated models.json")
    gen_p.add_argument("--providers", required=True, help="Space-separated list of selected providers")
    gen_p.add_argument("--custom-names", default="", help="Pipe-separated list of custom endpoint local IDs")
    gen_p.add_argument("--custom-displays", default="", help="Pipe-separated list of custom endpoint display names")
    gen_p.add_argument("--ollama-models", default="", help="Comma-separated list of Ollama model names")

    return parser


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "list":
        _cmd_list(args)
    elif args.command == "generate":
        _cmd_generate(args)
