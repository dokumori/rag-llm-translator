"""
token_tracker.py — Lightweight token usage tracker.

Accumulates prompt/completion token counts from OpenAI SDK response objects
and produces a human-readable summary with optional cost estimation.

Pricing data is NOT hardcoded here.  Instead, callers read pricing from the
project's ``models.json`` / ``custom/models.json`` config (via
``load_models_config()``) and pass the per-model rates into the constructor.
This means users can control pricing entirely through their model config files
without touching any source code.

Usage:
    from core.config import load_models_config
    from core.token_tracker import TokenTracker

    models = load_models_config()
    model_cfg = next((m for m in models if m["id"] == model_id), {})
    pricing = model_cfg.get("pricing", {})

    tracker = TokenTracker(
        model=model_id,
        cost_per_1k_prompt=pricing.get("prompt_per_1k_tokens"),
        cost_per_1k_completion=pricing.get("completion_per_1k_tokens"),
    )

    # After each LLM call:
    tracker.record(response.usage)

    # At the end of a run:
    tracker.print_summary()
    tracker.save("/path/to/output/")
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def build_price_table_from_config(models_config: List[Dict]) -> Dict[str, tuple]:
    """
    Build a ``{model_id: (prompt_per_1k, completion_per_1k)}`` dict from the
    list returned by ``load_models_config()``.

    Only entries that carry a ``"pricing"`` sub-object with both
    ``"prompt_per_1k_tokens"`` and ``"completion_per_1k_tokens"`` keys are
    included; all other entries are silently skipped.

    Example models.json entry:

        {
          "id": "claude-opus-4-20250514-v1",
          "name": "Claude Opus 4",
          "is_dry_run": false,
          "pricing": {
            "prompt_per_1k_tokens": 0.015,
            "completion_per_1k_tokens": 0.075
          }
        }
    """
    table = {}
    for m in models_config:
        model_id = m.get("id")
        pricing = m.get("pricing")
        if not model_id or not isinstance(pricing, dict):
            continue
        prompt_rate = pricing.get("prompt_per_1k_tokens")
        completion_rate = pricing.get("completion_per_1k_tokens")
        if prompt_rate is not None and completion_rate is not None:
            try:
                table[model_id] = (float(prompt_rate), float(completion_rate))
            except (TypeError, ValueError):
                logger.warning(
                    "⚠️  Invalid pricing for model '%s'; skipping cost estimation.",
                    model_id,
                )
    return table


@dataclass
class TokenTracker:
    """
    Accumulates token usage across multiple LLM calls for a single model.

    Pricing is optional: pass ``cost_per_1k_prompt`` and
    ``cost_per_1k_completion`` (both in USD) to enable cost estimation.
    These values are sourced from the ``"pricing"`` field in
    ``models.json`` / ``custom/models.json``.

    Args:
        model:                  Model ID string (for display only).
        cost_per_1k_prompt:     USD cost per 1,000 prompt tokens, or None.
        cost_per_1k_completion: USD cost per 1,000 completion tokens, or None.
    """

    model: str
    cost_per_1k_prompt: Optional[float] = None
    cost_per_1k_completion: Optional[float] = None

    # Running totals — updated by record()
    prompt_tokens: int = field(default=0, init=False)
    completion_tokens: int = field(default=0, init=False)
    total_tokens: int = field(default=0, init=False)
    request_count: int = field(default=0, init=False)

    def record(self, usage: object) -> None:
        """
        Extract token counts from an OpenAI CompletionUsage object and add
        them to the running totals.

        ``usage`` is the ``.usage`` attribute on a ``ChatCompletion`` response.
        It may be ``None`` (e.g. dry-run responses) — those are silently skipped.
        """
        if usage is None:
            return

        # Support both attribute-access (SDK object) and dict-style (mocked/JSON)
        def _get(key: str) -> int:
            if isinstance(usage, dict):
                return int(usage.get(key) or 0)
            return int(getattr(usage, key, 0) or 0)

        p = _get("prompt_tokens")
        c = _get("completion_tokens")
        t = _get("total_tokens") or (p + c)

        self.prompt_tokens += p
        self.completion_tokens += c
        self.total_tokens += t
        self.request_count += 1

    # ------------------------------------------------------------------
    # Cost estimation
    # ------------------------------------------------------------------

    def estimated_cost_usd(self) -> Optional[float]:
        """
        Return the estimated USD cost for tokens recorded so far.

        Returns ``None`` if no pricing data was supplied at construction time.
        """
        if self.cost_per_1k_prompt is None or self.cost_per_1k_completion is None:
            return None
        return (
            self.prompt_tokens / 1000 * self.cost_per_1k_prompt
            + self.completion_tokens / 1000 * self.cost_per_1k_completion
        )

    # ------------------------------------------------------------------
    # Output helpers
    # ------------------------------------------------------------------

    def summary_lines(self) -> list[str]:
        """Return a list of formatted summary lines (no log calls)."""
        cost = self.estimated_cost_usd()
        lines = [
            "\u2550" * 45,
            "\U0001f4b0 TOKEN USAGE SUMMARY",
            "\u2550" * 45,
            f"  Model           : {self.model}",
            f"  Requests        : {self.request_count}",
            f"  Prompt tokens   : {self.prompt_tokens:,}",
            f"  Completion tok. : {self.completion_tokens:,}",
            f"  Total tokens    : {self.total_tokens:,}",
        ]
        if cost is not None:
            lines.append(f"  Est. cost (USD) : ${cost:.4f}")
        else:
            lines.append(
                "  Est. cost (USD) : N/A "
                "(add \"pricing\" to this model in models.json to enable)"
            )
        lines.append("\u2550" * 45)
        return lines

    def print_summary(self) -> None:
        """Log the usage summary at INFO level."""
        if self.request_count == 0:
            logger.info("\U0001f4b0 TOKEN USAGE: No LLM requests were recorded.")
            return
        for line in self.summary_lines():
            logger.info(line)

    def to_dict(self) -> Dict:
        """Serialise the tracker state to a plain dict (JSON-safe)."""
        cost = self.estimated_cost_usd()
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": self.model,
            "request_count": self.request_count,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": round(cost, 6) if cost is not None else None,
        }

    def save(self, path: str) -> None:
        """
        Persist the usage summary to a JSON file.

        If ``path`` is a directory, a timestamped filename is generated inside it.
        The parent directory is created automatically if it does not exist.
        """
        if os.path.isdir(path):
            ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            model_slug = self.model.lower().replace("/", "-").replace(" ", "-")
            path = os.path.join(path, f"token_usage_{ts}_{model_slug}.json")

        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
            logger.info("\U0001f4be Token usage saved to: %s", path)
        except OSError as exc:
            logger.warning("\u26a0\ufe0f  Could not save token usage to %s: %s", path, exc)
