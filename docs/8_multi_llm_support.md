# Multi-LLM Provider Support

The RAG-LLM Translator connects to LLM providers via the built-in **LiteLLM gateway** container. You do not need to change any source code to switch providers.

All LLM traffic routes through the gateway (`http://litellm:4000/v1`), which translates each provider's native API into the OpenAI format transparently.

---

## Gateway Mode

The LiteLLM gateway is a required service — it starts automatically with `docker compose up -d`. Configure which providers to use by running the setup wizard:

```bash
bash bin/setup.sh
```

The wizard lets you choose one or more providers, collects API keys (hidden input), and auto-generates:
- `config/models.yaml` — single source of truth for all model definitions
- `config/litellm/config.yaml` — auto-derived from `models.yaml` (do not edit directly)

### Manual Setup

If you prefer to configure manually:

#### Step 1: Create your config file

```bash
cp config/models.example.yaml config/models.yaml
```

Edit `config/models.yaml` and uncomment the entries for providers you want to use.

#### Step 2: Generate the LiteLLM config

```bash
docker compose exec toolbox python3 /app/bin/lib/model_config.py generate-litellm \
    --models /app/config/models.yaml \
    --output /app/config/litellm/config.yaml
```

Or you can write `config/litellm/config.yaml` by hand — see the schema below.

#### Step 3: Set provider API keys in `.env`

Add the relevant API keys for the providers you want to use:

```bash
# Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Google Gemini
GEMINI_API_KEY=AI...

# OpenAI
OPENAI_API_KEY=sk-...

# Mistral
MISTRAL_API_KEY=...
```

#### Step 4: Start (or restart)

```bash
docker compose up -d
```

> [!TIP]
> The gateway starts automatically — no `--profile` flag is needed.

---

## Supported Providers

| Provider | Gateway mode | Notes |
|---|---|---|
| amazee.ai | ✅ | Use the `Custom` option in the setup wizard |
| OpenAI GPT-4o | ✅ | — |
| OpenAI o-series / GPT-5 | ✅ | LiteLLM auto-handles temperature / max_completion_tokens |
| **Anthropic Claude** | ✅ | Non-OpenAI API — handled by LiteLLM |
| **Google Gemini** | ✅ | Non-OpenAI API — handled by LiteLLM |
| Mistral | ✅ | — |
| Meta Llama (via hosts) | ✅ | Together AI, Groq, Fireworks — use the `Custom` option |
| Kimi K2.5 | ✅ | OpenRouter or Moonshot AI — use the `Custom` option |
| Ollama (self-hosted) | ✅ | Use the `Local` mode in the setup wizard |
| Any OpenAI-compatible URL | ✅ | Use the `Custom` option in the setup wizard |

---

## Adding or Editing Models

All model definitions live in a single file: **`config/models.yaml`**.

```yaml
# config/models.yaml example
models:
  - id: claude-sonnet-4-6
    name: Claude Sonnet 4.6
    provider: anthropic
    model: claude-sonnet-4-6
    api_key_env: ANTHROPIC_API_KEY
    pricing:
      prompt_per_1k_tokens: 0.003
      completion_per_1k_tokens: 0.015

  - id: dry-run-dummy
    name: Dry Run (No API calls)
    is_dry_run: true
```

After editing `config/models.yaml`, regenerate the LiteLLM config and restart:

```bash
docker compose exec toolbox python3 /app/bin/lib/model_config.py generate-litellm \
    --models /app/config/models.yaml \
    --output /app/config/litellm/config.yaml

docker compose restart litellm
```

### Field Reference

| Field | Required | Notes |
|---|---|---|
| `id` | ✅ | Short identifier used by `--model` flag and menus (no spaces) |
| `name` | ✅ | Display name in translation/evaluation menus |
| `provider` | ✅ (non-dry-run) | `anthropic` \| `google` \| `openai` \| `mistral` \| `ollama` \| `custom` |
| `model` | ✅ (non-dry-run) | API model identifier (without provider prefix) |
| `api_key_env` | for most providers | Name of the env var holding the API key |
| `api_base_env` | for `custom`/`ollama` | Name of the env var holding the base URL |
| `is_dry_run` | dry-run only | Set `true` for the no-API-calls sentinel |
| `pricing` | optional | `prompt_per_1k_tokens` / `completion_per_1k_tokens` in USD |

---

## Troubleshooting

**`Translation provider unavailable` (502)**
- Check `docker compose logs rag-proxy` for the upstream error
- Verify `config/models.yaml` has an entry for the model you selected
- Check `docker compose logs litellm` for provider-side errors
- Ensure the relevant API key is set in `.env`

**Gateway container not starting**
- Ensure `config/litellm/config.yaml` has at least one model entry — LiteLLM requires at least one configured model to start
- Run `docker compose logs litellm` to see the startup error
- Regenerate with: `docker compose exec toolbox python3 /app/bin/lib/model_config.py generate-litellm --models /app/config/models.yaml --output /app/config/litellm/config.yaml`

---

## Using Custom OpenAI-Compatible Endpoints via Gateway

If you have one or more OpenAI-compatible endpoints (e.g. amazee.ai, vLLM, a corporate API gateway), add them to `config/models.yaml` with `provider: custom`:

### Setup via Wizard (recommended)

Run `bash bin/setup.sh`, choose **Gateway** mode, and select **5) Custom**.
The wizard will ask for each endpoint:

- **Local ID** — the name used internally to route requests (e.g. `amazee-llama3`)
- **Menu label** — the name shown in translation/evaluation menus
- **Remote model ID** — the identifier your endpoint expects (e.g. `llama-3.1-70b-instruct`)
- **Base URL** — your endpoint's URL (e.g. `https://llm.us104.amazee.ai/v1`)
- **API Key** — your endpoint's authentication token

After each endpoint, you'll be asked **"Add another custom endpoint?"** — answer `y` to add more.

The wizard automatically writes `config/models.yaml` and derives `config/litellm/config.yaml`.

### Manual Setup

1. Add to `.env`:
   ```bash
   CUSTOM_LLM_BASE_URL_1=https://llm.us104.amazee.ai/v1
   CUSTOM_LLM_API_KEY_1=sk-your-key
   CUSTOM_LLM_BASE_URL_2=https://api.example.com/v1
   CUSTOM_LLM_API_KEY_2=sk-another-key
   ```

2. Add to `config/models.yaml`:
   ```yaml
   - id: amazee-llama3
     name: "amazee.ai — Llama 3.1"
     provider: custom
     model: llama-3.1-70b-instruct
     api_base_env: CUSTOM_LLM_BASE_URL_1
     api_key_env: CUSTOM_LLM_API_KEY_1

   - id: example-gpt
     name: "Example — GPT-4o"
     provider: custom
     model: gpt-4o
     api_base_env: CUSTOM_LLM_BASE_URL_2
     api_key_env: CUSTOM_LLM_API_KEY_2
   ```

3. Regenerate LiteLLM config and restart:
   ```bash
   docker compose exec toolbox python3 /app/bin/lib/model_config.py generate-litellm \
       --models /app/config/models.yaml \
       --output /app/config/litellm/config.yaml
   docker compose restart litellm
   ```

> [!NOTE]
> The `custom` provider maps to the openai-compatible client with a custom `api_base`.
> Variable names in `.env` are completely free-form — the wizard uses `CUSTOM_LLM_BASE_URL_N` / `CUSTOM_LLM_API_KEY_N` but any name works.

---

## Using Ollama via Gateway

Routing Ollama through the gateway lets you use local models **alongside** cloud providers in the same session without changing any config.

### Prerequisites

1. **Ollama must be running** on the host machine.
2. **Ollama must accept external connections** — set `OLLAMA_HOST=0.0.0.0` before starting Ollama (otherwise it only listens on `127.0.0.1` and Docker containers cannot reach it).
3. **Linux only:** The shipped `docker-compose.yml` already includes `extra_hosts: ["host.docker.internal:host-gateway"]` on the `litellm` service.

### Setup via Wizard (recommended)

Run `bash bin/setup.sh`, choose **Local** mode.
Enter your model names (comma-separated). The wizard sets `OLLAMA_BASE_URL` in `.env` and writes `config/models.yaml` with the Ollama entries automatically.

### Manual Setup

1. Add to `.env`:
   ```bash
   OLLAMA_BASE_URL=http://host.docker.internal:11434
   ```

2. Add to `config/models.yaml`:
   ```yaml
   - id: llama3.1
     name: "Ollama — llama3.1"
     provider: ollama
     model: llama3.1
     api_base_env: OLLAMA_BASE_URL
   ```

3. Regenerate and restart:
   ```bash
   docker compose exec toolbox python3 /app/bin/lib/model_config.py generate-litellm \
       --models /app/config/models.yaml \
       --output /app/config/litellm/config.yaml
   docker compose restart litellm
   ```

> [!TIP]
> You can mix Ollama models with cloud providers in the same `models.yaml`. After setup, simply select your Ollama model name in the translation or evaluation menus.
