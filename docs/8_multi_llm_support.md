# Multi-LLM Provider Support

The RAG-LLM Translator supports connecting to any LLM provider via two modes. You do not need to change any source code to switch providers.

---

## Direct Mode (Default)

In direct mode, `rag-proxy` talks to an upstream LLM endpoint that is already OpenAI-compatible. This is the default configuration and requires no additional containers.

**Providers that work out of the box in direct mode:**

| Provider | Example `LLM_BASE_URL` |
|---|---|
| amazee.ai | `https://llm.us104.amazee.ai/v1` |
| OpenRouter | `https://openrouter.ai/api/v1` |
| Ollama (self-hosted) | `http://host.docker.internal:11434/v1` |
| Mistral AI | `https://api.mistral.ai/v1` |
| OpenAI | `https://api.openai.com/v1` |
| Together AI / Groq / Fireworks | Provider-specific URL |

Set these in your `.env` file:

```bash
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_TOKEN=sk-...
```

### OpenAI o-series and GPT-5 (direct mode)

OpenAI's newer reasoning models (`o3-mini`, `o4-mini`, and GPT-5 series) have different API requirements — they reject `temperature` and require `max_completion_tokens` instead of `max_tokens`. The system handles this automatically using per-model flags in `config/models/models.json`.

To use these models directly (without the gateway), ensure the model is listed in `models.json` (or `config/models/custom/models.json`) with the appropriate flags:

```json
{
  "id": "o4-mini",
  "name": "OpenAI o4-mini",
  "is_dry_run": false,
  "omit_temperature": true,
  "use_max_completion_tokens": true
}
```

Example entries for `gpt-4o`, `o3-mini`, and `o4-mini` are included in `config/models/custom/models.example.json`. Copy that file to `config/models/custom/models.json` and edit as needed.

---

## Gateway Mode (Optional — LiteLLM)

For providers whose APIs are **not** OpenAI-compatible (Anthropic, Google Gemini), or when you want centralised API key management and retry logic, you can run the optional **LiteLLM** gateway container.

LiteLLM translates all provider APIs into the OpenAI format transparently. Your `rag-proxy` always speaks OpenAI — LiteLLM handles the rest.

### Step 1: Create your config file

`config/litellm/config.yaml` is git-ignored and must be created from the example before starting the gateway:

```bash
cp config/litellm/config.example.yaml config/litellm/config.yaml
```

### Step 2: Enable the models you need

Edit `config/litellm/config.yaml` and uncomment entries for the providers you want to use:

```yaml
model_list:
  - model_name: claude-haiku-4-5
    litellm_params:
      model: anthropic/claude-haiku-4-5-20251001
      api_key: os.environ/ANTHROPIC_API_KEY
```

The `model_name` must match the `id` of an entry in your `models.json`. In `config/models/models.json` (or `config/models/custom/models.json`):

```json
{
  "id": "claude-haiku-4-5",
  "name": "Claude Haiku 4.5",
  "is_dry_run": false
}
```

### Step 3: Set provider API keys in `.env`

Add the relevant API keys for the providers you want to use:

```bash
# Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Google Gemini
GEMINI_API_KEY=AI...

# OpenAI (if routing through LiteLLM)
OPENAI_API_KEY=sk-...

# Mistral (if routing through LiteLLM)
MISTRAL_API_KEY=...
```

### Step 4: Start the gateway

```bash
docker compose --profile gateway up -d
```

This starts the `litellm` container on port `4000`. If `config.yaml` is missing, the container will print an error with the exact copy command and exit cleanly.

> [!TIP]
> **Make it permanent:** If you want the gateway to always start with `docker compose up` without needing the `--profile` flag, add `COMPOSE_PROFILES=gateway` to your `.env` file.

### Step 5: Point `rag-proxy` at the gateway

Update these values in your `.env`:

```bash
LLM_BASE_URL=http://litellm:4000/v1
LLM_API_TOKEN=sk-anything   # LiteLLM uses per-model keys from config.yaml; this value is ignored
```

### Step 6: Restart `rag-proxy`

```bash
docker compose up -d --force-recreate rag-proxy
```

---

## Supported Providers

| Provider | Direct mode | Gateway mode | Notes |
|---|---|---|---|
| amazee.ai | ✅ | — | Multi-model gateway already included |
| OpenAI GPT-4o | ✅ | ✅ | Direct works; gateway adds retry/fallback |
| OpenAI o-series / GPT-5 | ✅ | ✅ | Direct works via model flags; gateway auto-handles |
| **Anthropic Claude** | ❌ | ✅ | Non-OpenAI API — gateway required |
| **Google Gemini** | ❌ | ✅ | Non-OpenAI API — gateway required |
| Mistral | ✅ | ✅ | Already OpenAI-compatible |
| Meta Llama (via hosts) | ✅ | ✅ | Together AI, Groq, Fireworks are all compatible |
| Kimi K2.5 | ✅ | ✅ | OpenRouter or Moonshot AI direct |
| Ollama (self-hosted) | ✅ | — | Use `host.docker.internal` as hostname |

---

## Custom Model List

If you want to use models not in the default `config/models/models.json`, create a custom override:

1. Copy `config/models/custom/models.example.json` to `config/models/custom/models.json`
2. Add or edit model entries
3. Restart `rag-proxy` — custom models are loaded automatically

When a custom `models.json` is present it replaces the base model list entirely (the dry-run sentinel is always preserved). See comments in `config/models/models.json` for available flags.

---

## Troubleshooting

**`Translation provider unavailable` (502)**
- Check `docker compose logs rag-proxy` for the upstream error
- Verify `LLM_BASE_URL` and `LLM_API_TOKEN` in `.env`
- If using gateway mode, check `docker compose logs litellm`

**Model returns an error about `temperature`**
- Add `"omit_temperature": true` to the model entry in `models.json`

**Model returns an error about `max_tokens`**
- Add `"use_max_completion_tokens": true` to the model entry in `models.json`

**Gateway container not starting**
- Ensure `config/litellm/config.yaml` has at least one uncommented model entry — LiteLLM requires at least one configured model to start
