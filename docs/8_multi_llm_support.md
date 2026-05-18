# Multi-LLM Provider Support

The RAG-LLM Translator connects to LLM providers via the built-in **LiteLLM gateway** container. You do not need to change any source code to switch providers.

All LLM traffic routes through the gateway (`http://litellm:4000/v1`), which translates each provider's native API into the OpenAI format transparently.

---

## Gateway Mode

The LiteLLM gateway is a required service — it starts automatically with `docker compose up -d`. Configure which providers to use by running the setup wizard:

```bash
bash bin/setup.sh
```

The wizard lets you choose one or more providers, collects API keys (hidden input), and auto-generates `config/litellm/config.yaml` and `config/models/custom/models.json`.

### Manual Setup

If you prefer to configure manually:

#### Step 1: Create your config file

```bash
cp config/litellm/config.example.yaml config/litellm/config.yaml
```

#### Step 2: Enable the models you need

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
- Verify `config/litellm/config.yaml` has an entry for the model you selected
- Check `docker compose logs litellm` for provider-side errors
- Ensure the relevant API key is set in `.env`

**Gateway container not starting**
- Ensure `config/litellm/config.yaml` has at least one uncommented model entry — LiteLLM requires at least one configured model to start
- Run `docker compose logs litellm` to see the startup error

---

## Using Custom OpenAI-Compatible Endpoints via Gateway

If you have one or more OpenAI-compatible endpoints (e.g. amazee.ai, vLLM, a corporate API gateway),
you can route them through the LiteLLM gateway alongside Claude, Gemini, and other providers.

### Setup via Wizard (recommended)

Run `bash bin/setup.sh`, choose **Gateway** mode, and select **5) Custom**.
The wizard will ask for each endpoint:

- **Local ID** — the name used internally to route requests (e.g. `amazee-llama3`)
- **Menu label** — the name shown in translation/evaluation menus
- **Remote model ID** — the identifier your endpoint expects (e.g. `llama-3.1-70b-instruct`)
- **Base URL** — your endpoint's URL (e.g. `https://llm.us104.amazee.ai/v1`)
- **API Key** — your endpoint's authentication token

After each endpoint, you'll be asked **"Add another custom endpoint?"** — answer `y` to add more.

The wizard automatically writes `.env`, `config/litellm/config.yaml`, and
`config/models/custom/models.json` for all configured endpoints.

### Manual Setup

The `litellm` container loads `.env` directly, so any variable name you define there is
automatically available. You can add as many endpoints as you like.

1. Add to `.env`:
   ```bash
   CUSTOM_LLM_BASE_URL_1=https://llm.us104.amazee.ai/v1
   CUSTOM_LLM_API_KEY_1=sk-your-key
   CUSTOM_LLM_BASE_URL_2=https://api.example.com/v1
   CUSTOM_LLM_API_KEY_2=sk-another-key
   ```

2. Add to `config/litellm/config.yaml`:
   ```yaml
   - model_name: amazee-llama3
     litellm_params:
       model: openai/llama-3.1-70b-instruct
       api_base: os.environ/CUSTOM_LLM_BASE_URL_1
       api_key: os.environ/CUSTOM_LLM_API_KEY_1

   - model_name: example-gpt
     litellm_params:
       model: openai/gpt-4o
       api_base: os.environ/CUSTOM_LLM_BASE_URL_2
       api_key: os.environ/CUSTOM_LLM_API_KEY_2
   ```
   The `model` value after `openai/` must be the model identifier your remote server expects.

3. Add to `config/models/custom/models.json`:
   ```json
   { "id": "amazee-llama3", "name": "Amazee Llama 3", "is_dry_run": false },
   { "id": "example-gpt", "name": "Example GPT", "is_dry_run": false }
   ```

4. Restart:
   ```bash
   docker compose up -d
   ```

> [!NOTE]
> The `openai/` prefix with a custom `api_base` tells LiteLLM to use an OpenAI-compatible
> client pointed at your endpoint instead of the official OpenAI API.
>
> Variable names in `.env` are completely free-form — use any convention you like. The wizard
> uses `CUSTOM_LLM_BASE_URL_N` / `CUSTOM_LLM_API_KEY_N` for the entries it generates, but
> manual additions can use any name and will work without touching `docker-compose.yml`.


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

Run `bash bin/setup.sh`, choose **Local** mode.
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

4. Start:
   ```bash
   docker compose up -d
   ```

> [!TIP]
> You can mix Ollama models with cloud providers in the same `config.yaml`. After setup,
> simply select your Ollama model name in the translation or evaluation menus.
