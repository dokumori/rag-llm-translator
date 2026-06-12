"""
bin/lib/model_config.py
-----------------------
Shared Python module for model configuration logic used by shell scripts
and Docker containers.

Provides:
  - load_models_yaml()         : load models from a single models.yaml file
  - generate_litellm_config()  : derive config/litellm/config.yaml from config/models/models.yaml

CLI subcommands:
  python3 bin/lib/model_config.py list            --models <path> --format names|json|lookup [--name <name>]
  python3 bin/lib/model_config.py validate-model  --name <model>
  python3 bin/lib/model_config.py generate-litellm --models <path> --output <path>
  python3 bin/lib/model_config.py generate         --models <path> --output <path> --providers <str> [options]
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Provider → LiteLLM prefix mapping
# ---------------------------------------------------------------------------

_PROVIDER_PREFIX: dict[str, str] = {
    "anthropic": "anthropic",
    "google":    "gemini",
    "openai":    "openai",
    "mistral":   "mistral",
    "ollama":    "ollama",
    "custom":    "openai",   # custom endpoints use openai-compatible client
}

# Provider prefixes used by generate() to filter example entries by id prefix
_PROVIDER_ID_PREFIXES: dict[str, list[str]] = {
    "anthropic": ["claude-"],
    "google":    ["gemini-"],
    "openai":    ["gpt-", "o3"],
    "mistral":   ["mistral-"],
}

# ---------------------------------------------------------------------------
# Embedding model blocklist
# ---------------------------------------------------------------------------
# Models that require query:/passage: prefixes -- incompatible with this
# application.  This is the SINGLE SOURCE OF TRUTH for the blocklist.
# Must be kept in sync with services/shared/src/infrastructure.py which
# maintains a copy for the in-container runtime check.
# See docs/7_embedding_model.md for model requirements.
_BLOCKED_MODEL_PATTERNS: list[str] = [
    "intfloat/e5-",
    "intfloat/multilingual-e5-",
]


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def load_models_yaml(yaml_path: str) -> list[dict]:
    """
    Load models from a single models.yaml file.

    Returns a list of model dicts with the same shape callers already expect:
      [{"id": ..., "name": ..., "is_dry_run": ..., "pricing": {...}}, ...]

    Ordering: regular models first, dry-run last.
    Dry-run entries automatically receive ' (dry run)' in their name if missing.
    Raises FileNotFoundError if yaml_path does not exist.
    """
    import yaml  # available inside containers; host invocations go via docker exec

    text = Path(yaml_path).read_text(encoding="utf-8")
    data: dict = yaml.safe_load(text) or {}
    models: list[dict] = data.get("models", [])

    # Separate regular models from dry-run sentinels so dry-runs always come last.
    regular = [m for m in models if not m.get("is_dry_run")]
    dry_runs = [m for m in models if m.get("is_dry_run")]

    # Ensure dry-run entries are labelled as such in their display name.
    for m in dry_runs:
        if "(dry run)" not in m.get("name", "").lower():
            m["name"] = f"{m['name']} (dry run)"

    return regular + dry_runs


def generate_litellm_config(models_yaml_path: str, output_path: str) -> None:
    """
    Derive config/litellm/config.yaml from a models.yaml file.

    Dry-run entries are skipped (they have no LiteLLM routing).
    The output file is written with a header comment warning it is auto-generated.
    """
    import yaml

    data: dict = yaml.safe_load(Path(models_yaml_path).read_text(encoding="utf-8")) or {}
    models: list[dict] = data.get("models", [])

    # Build the LiteLLM model_list, skipping dry-run entries.
    model_list: list[dict[str, Any]] = []
    for m in models:
        if m.get("is_dry_run"):
            continue

        # Resolve the LiteLLM model string (e.g. "openai/gpt-4o").
        provider = m.get("provider", "")
        prefix = _PROVIDER_PREFIX.get(provider, provider)
        model_id = m.get("model", m["id"])

        params: dict[str, str] = {
            # Only prepend the provider prefix when model_id doesn't already
            # include one (e.g. "gemini/gemini-2.5-flash" must not become
            # "gemini/gemini/gemini-2.5-flash").
            "model": model_id if "/" in model_id else f"{prefix}/{model_id}",
        }
        # Reference API credentials via environment variables rather than hard-coding them.
        if m.get("api_key_env"):
            params["api_key"] = f"os.environ/{m['api_key_env']}"
        if m.get("api_base_env"):
            params["api_base"] = f"os.environ/{m['api_base_env']}"

        model_list.append({
            "model_name": m["id"],
            "litellm_params": params,
        })

    # Assemble the top-level LiteLLM config structure.
    config = {
        "litellm_settings": {
            "drop_params": True,
        },
        "model_list": model_list,
    }

    # Prepend a comment block.
    header = (
        f"# LiteLLM Gateway Configuration\n"
        f"# Auto-generated from config/models/models.yaml on {datetime.now():%Y-%m-%d %H:%M}\n"
        f"# Do NOT edit this file directly — edit config/models/models.yaml instead.\n"
        f"# Regenerate with: python3 bin/lib/model_config.py generate-litellm "
        f"--models config/models/models.yaml --output config/litellm/config.yaml\n\n"
    )
    content = header + yaml.dump(config, default_flow_style=False, sort_keys=False)

    # Write to stdout or to a file.
    if output_path == "-":
        sys.stdout.write(content)
    else:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")


def generate_models_yaml(
    example_path: str,
    output_path: str,
    providers: list[str],
    custom_entries: list[dict] | None = None,
    ollama_models: list[str] | None = None,
) -> None:
    """
    Build a models.yaml from provider selections and write it to output_path.

    - Filter example entries by provider prefix.
    - Append custom endpoint entries (if 'custom' in providers).
    - Append Ollama entries (if 'ollama' in providers).
    - Always include the dry-run entry.
    - Writes the result to output_path.
    """
    import yaml

    data: dict = yaml.safe_load(Path(example_path).read_text(encoding="utf-8")) or {}
    example_models: list[dict] = data.get("models", [])

    # Strip comments from example by round-tripping through safe_load (already done above)
    selected: list[dict] = []

    # Keep only the example entries whose model ID matches one of the known
    # prefixes for a selected provider (e.g. "gpt-" for openai, "gemini-" for
    # google).  Dry-run entries are excluded here and re-added unconditionally
    # at the end so they always appear last.
    for m in example_models:
        if m.get("is_dry_run"):
            continue
        mid = m.get("id", "")
        for p in providers:
            if any(mid.startswith(pfx) for pfx in _PROVIDER_ID_PREFIXES.get(p, [])):
                selected.append(m)
                break

    # Custom OpenAI-compatible endpoint entries
    if "custom" in providers and custom_entries:
        for entry in custom_entries:
            if entry.get("id"):
                selected.append({
                    "id": entry["id"],
                    "name": entry.get("name", entry["id"]),
                    "provider": "custom",
                    "model": entry.get("remote_model", entry["id"]),
                    "api_base_env": entry.get("api_base_env", "CUSTOM_LLM_BASE_URL_1"),
                    "api_key_env": entry.get("api_key_env", "CUSTOM_LLM_API_KEY_1"),
                    "is_dry_run": False,
                })

    # Ollama entries
    if "ollama" in providers and ollama_models:
        for raw in ollama_models:
            model = raw.strip()
            if model:
                selected.append({
                    "id": model,
                    "name": f"Ollama \u2014 {model}",
                    "provider": "ollama",
                    "model": model,
                    "api_base_env": "OLLAMA_BASE_URL",
                    "is_dry_run": False,
                })

    # Always include dry-run last
    dry_run = next((m for m in example_models if m.get("is_dry_run")), None)
    if dry_run:
        selected.append(dry_run)

    # Prepend a comment block.
    header = (
        "# config/models/models.yaml — Single source of truth for all model definitions.\n"
        f"# Generated by bin/setup.sh on {datetime.now():%Y-%m-%d %H:%M}\n"
        "# After editing: docker compose restart litellm\n"
        "# config/litellm/config.yaml is auto-generated from this file.\n\n"
    )
    content = header + yaml.dump({"models": selected}, default_flow_style=False, sort_keys=False)

    # print to stdout; otherwise write to the given path, creating parent directories as needed.
    if output_path == "-":
        sys.stdout.write(content)
    else:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def _cmd_list(args: argparse.Namespace) -> None:
    models = load_models_yaml(args.models)

    # Print one model name per line.
    if args.format == "names":
        for m in models:
            print(m["name"])

    # Print each model as a JSON object on its own line.
    elif args.format == "json":
        import json
        for m in models:
            print(json.dumps(m))

    # Print the model id, is_dry_run flag, and provider for a single model looked up by name.
    elif args.format == "lookup":
        if not args.name:
            print("error: --name is required for --format lookup", file=sys.stderr)
            sys.exit(1)
        match = next((m for m in models if m["name"] == args.name), None)
        if match is None:
            print(f"error: model not found: {args.name!r}", file=sys.stderr)
            sys.exit(1)
        print(match["id"])
        print(str(match.get("is_dry_run", False)).lower())
        print(match.get("provider", ""))

    else:
        print(f"error: unknown format: {args.format!r}", file=sys.stderr)
        sys.exit(1)


def _cmd_generate_litellm(args: argparse.Namespace) -> None:
    # Derive config/litellm/config.yaml from models.yaml.
    generate_litellm_config(args.models, args.output)


def _cmd_generate(args: argparse.Namespace) -> None:
    # Split the space-separated providers string into a list.
    providers = args.providers.split() if args.providers else []

    # Reconstruct each custom endpoint's fields from parallel pipe-separated strings.
    custom_entries: list[dict] = []
    if args.custom_names:
        names = [n for n in args.custom_names.split("|") if n]
        displays = [d for d in args.custom_displays.split("|") if d] if args.custom_displays else []
        remotes = [r for r in args.custom_remotes.split("|") if r] if args.custom_remotes else []
        base_envs = [b for b in args.custom_base_envs.split("|") if b] if args.custom_base_envs else []
        key_envs = [k for k in args.custom_key_envs.split("|") if k] if args.custom_key_envs else []
        for i, name in enumerate(names):
            custom_entries.append({
                "id": name,
                "name": displays[i] if i < len(displays) else name,
                "remote_model": remotes[i] if i < len(remotes) else name,
                "api_base_env": base_envs[i] if i < len(base_envs) else f"CUSTOM_LLM_BASE_URL_{i+1}",
                "api_key_env": key_envs[i] if i < len(key_envs) else f"CUSTOM_LLM_API_KEY_{i+1}",
            })

    # Split the comma-separated Ollama model names into a list.
    ollama_models: list[str] | None = None
    if args.ollama_models:
        ollama_models = [m for m in args.ollama_models.split(",") if m.strip()]

    generate_models_yaml(
        example_path=args.example,
        output_path=args.output,
        providers=providers,
        custom_entries=custom_entries if custom_entries else None,
        ollama_models=ollama_models,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="model_config",
        description="Model configuration utilities for the RAG-LLM Translator.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # -- list subcommand --
    list_p = sub.add_parser("list", help="List models from models.yaml.")
    list_p.add_argument("--models", required=True, help="Path to models.yaml")
    list_p.add_argument(
        "--format",
        required=True,
        choices=["names", "json", "lookup"],
        help="Output format: names | json | lookup",
    )
    list_p.add_argument("--name", default=None, help="Model name to look up (required for --format lookup)")

    # -- validate-model subcommand --
    val_p = sub.add_parser(
        "validate-model",
        help="Check whether a model name is compatible (not in the blocklist).",
    )
    val_p.add_argument("--name", required=True, help="Embedding model name to validate")

    # -- generate-litellm subcommand --
    gen_litellm_p = sub.add_parser(
        "generate-litellm",
        help="Generate config/litellm/config.yaml from models.yaml.",
    )
    gen_litellm_p.add_argument("--models", required=True, help="Path to models.yaml")
    gen_litellm_p.add_argument("--output", required=True, help="Path to write config.yaml (use '-' for stdout)")

    # -- generate subcommand (called by setup.sh) --
    gen_p = sub.add_parser("generate", help="Generate models.yaml from provider selections.")
    gen_p.add_argument("--example", required=True, help="Path to models.example.yaml source")
    gen_p.add_argument("--output", required=True, help="Path to write the generated models.yaml (use '-' for stdout)")
    gen_p.add_argument("--providers", required=True, help="Space-separated list of selected providers")
    gen_p.add_argument("--custom-names", default="", help="Pipe-separated list of custom endpoint local IDs")
    gen_p.add_argument("--custom-displays", default="", help="Pipe-separated list of custom endpoint display names")
    gen_p.add_argument("--custom-remotes", default="", help="Pipe-separated list of custom endpoint remote model IDs")
    gen_p.add_argument("--custom-base-envs", default="", help="Pipe-separated list of custom api_base_env var names")
    gen_p.add_argument("--custom-key-envs", default="", help="Pipe-separated list of custom api_key_env var names")
    gen_p.add_argument("--ollama-models", default="", help="Comma-separated list of Ollama model names")

    return parser


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()

    # Dispatch to the appropriate subcommand handler.
    if args.command == "list":
        _cmd_list(args)
    elif args.command == "validate-model":
        for pattern in _BLOCKED_MODEL_PATTERNS:
            if args.name.startswith(pattern):
                print(
                    f"Unsupported model: '{args.name}'\n"
                    f"Models matching '{pattern}*' require query:/passage: prefixes\n"
                    f"which are not supported by this application.\n"
                    f"See docs/7_embedding_model.md for compatible model requirements.",
                    file=sys.stderr,
                )
                sys.exit(1)
        print(f"ok")
    elif args.command == "generate-litellm":
        _cmd_generate_litellm(args)
    elif args.command == "generate":
        _cmd_generate(args)
