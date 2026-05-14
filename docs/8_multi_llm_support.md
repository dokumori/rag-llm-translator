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
| amazee.ai | ✅ | ✅ | Direct: single-endpoint; Gateway: alongside other providers |
| OpenAI GPT-4o | ✅ | ✅ | Direct works; gateway adds retry/fallback |
| OpenAI o-series / GPT-5 | ✅ | ✅ | Direct works via model flags; gateway auto-handles |
| **Anthropic Claude** | ❌ | ✅ | Non-OpenAI API — gateway required |
| **Google Gemini** | ❌ | ✅ | Non-OpenAI API — gateway required |
| Mistral | ✅ | ✅ | Already OpenAI-compatible |
| Meta Llama (via hosts) | ✅ | ✅ | Together AI, Groq, Fireworks are all compatible |
| Kimi K2.5 | ✅ | ✅ | OpenRouter or Moonshot AI direct |
| Ollama (self-hosted) | ✅ | ✅ | Direct: `host.docker.internal`; Gateway: `ollama/<model>` |
| Any OpenAI-compatible URL | ✅ | ✅ | Direct: single endpoint; Gateway: alongside all other providers |

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

---

## Using Custom OpenAI-Compatible Endpoints via Gateway

If you have an OpenAI-compatible endpoint (e.g. amazee.ai, vLLM, a corporate API gateway),
you can route it through the LiteLLM gateway. This lets you use it **alongside** Claude,
Gemini, and other providers without switching `.env` configuration.

### Setup via Wizard (recommended)

Run `bash bin/initial_setup.sh`, choose **Gateway** mode, and select **5) Custom**.
The wizard will ask for:

- **Model name** — the name shown in translation/evaluation menus (e.g. `amazee-llama3`)
- **Remote model ID** — the identifier your endpoint expects (e.g. `llama-3.1-70b-instruct`)
- **Base URL** — your endpoint's URL (e.g. `https://llm.us104.amazee.ai/v1`)
- **API Key** — your endpoint's authentication token

The wizard automatically writes `.env`, `config/litellm/config.yaml`, and
`config/models/custom/models.json`.

### Manual Setup

1. Add to `.env`:
   ```bash
   CUSTOM_LLM_BASE_URL=https://llm.us104.amazee.ai/v1
   CUSTOM_LLM_API_KEY=sk-your-key
   ```

2. Add to `config/litellm/config.yaml`:
   ```yaml
   - model_name: amazee-llama3
     litellm_params:
       model: openai/llama-3.1-70b-instruct
       api_base: os.environ/CUSTOM_LLM_BASE_URL
       api_key: os.environ/CUSTOM_LLM_API_KEY
   ```
   The `model` value after `openai/` must be the model identifier your remote server expects.

3. Add to `config/models/custom/models.json`:
   ```json
   { "id": "amazee-llama3", "name": "Amazee Llama 3", "is_dry_run": false }
   ```

4. Restart the gateway:
   ```bash
   docker compose up -d
   ```

> [!NOTE]
> The `openai/` prefix with a custom `api_base` tells LiteLLM to use an OpenAI-compatible
> client pointed at your endpoint instead of the official OpenAI API.

---

## Using Ollama via Gateway

Routing Ollama through the gateway lets you use local models **alongside** cloud providers
in the same session without changing any config.

### Prerequisites

1. **Ollama must be running** on the host machine.
2. **Ollama must accept external connections** — set `OLLAMA_HOST=0.0.0.0` before starting
   Ollama (otherwise it only listens on `127.0.0.1` and Docker containers cannot reach it).
3. **Linux only:** The shipped `docker-compose.yml` already includes
   `extra_hosts: ["host.docker.internal:host-gateway"]` on the `litellm` service, which is
   required for `host.docker.internal` to resolve on Linux. On macOS/Windows this is a no-op.

### Setup via Wizard (recommended)

Run `bash bin/initial_setup.sh`, choose **Gateway** mode, and select **6) Ollama**.
Enter your model names (comma-separated). The wizard sets `OLLAMA_BASE_URL` in `.env` and
generates the config and models entries automatically.

### Manual Setup

1. Add to `.env`:
   ```bash
   OLLAMA_BASE_URL=http://host.docker.internal:11434
   ```

2. Add to `config/litellm/config.yaml` (one entry per model):
   ```yaml
   - model_name: llama3.1
     litellm_params:
       model: ollama/llama3.1
       api_base: os.environ/OLLAMA_BASE_URL
   ```

3. Add to `config/models/custom/models.json`:
   ```json
   { "id": "llama3.1", "name": "Ollama — llama3.1", "is_dry_run": false }
   ```

4. Restart the gateway:
   ```bash
   docker compose up -d
   ```

> [!TIP]
> You can mix Ollama models with cloud providers in the same `config.yaml`. After setup,
> simply select your Ollama model name in the translation or evaluation menus.
