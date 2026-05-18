# RAG-LLM Translator: Context-Aware Localisation

The RAG-LLM Translator leverages LLMs and a Retrieval-Augmented Generation (RAG) architecture to automate PO file localisation for open-source projects using the gettext standard. Originally built as a translation aid for the Drupal community (https://www.drupal.org/project/translation_llm), it has since been generalised to support any gettext-compatible OSS project.

The system connects to any LLM provider via the built-in **LiteLLM gateway** container. Supported providers include Anthropic Claude, Google Gemini, OpenAI (including o-series reasoning models), Mistral, as well as private or self-hosted LLM providers such as amazee.ai, Ollama, and any OpenAI-compatible endpoint. Configure providers by running `bash bin/setup.sh`.


# How to use rag-llm-translator

## Prerequisites

Before getting started, make sure the following are in place:

- **Docker Desktop** (macOS / Windows) or Docker Engine with the Compose plugin (Linux) — installed and running
- A **bash-compatible terminal**
- **API credentials** for at least one supported LLM provider (Anthropic, Google, OpenAI, Mistral, amazee.ai, or any OpenAI-compatible endpoint), or [Ollama](https://ollama.com/) running locally

## Quick Start (Recommended)

The easiest way to get started is the interactive system menu:

```bash
bash bin/system_menu.sh
```

The menu covers the full setup lifecycle: configuring your LLM provider and API keys, downloading the embedding model (~1.3 GB, one-time), building and starting the Docker environment, preparing and ingesting your translation data, running translations, and tuning RAG thresholds. It detects the current state of your environment and shows contextual hints at each stage.

## Reference: Running commands manually

If you prefer to run steps individually, or need to troubleshoot a specific part of the pipeline, use the commands below.

> [!NOTE]
> Steps 1–3 are one-time setup. Once the stack is running and the embedding model is downloaded, you only need to repeat steps 4–6 for new translation projects.

### 1. Create the .env file

Run:
```bash
bash bin/setup.sh
```

...and supply the required information as prompted. The script handles:
- **LLM connection**: provider selection (Anthropic, Google, OpenAI, Mistral, custom endpoints, or Ollama) and API key collection
- **Batch size**: number of strings sent to the LLM per request (`BULK_SIZE`, default: 15)
- **Embedding model**: downloads the default model (~1.3 GB) as part of setup
- **Docker**: optionally starts the stack immediately after configuration

> [!NOTE]
> **RAG Sensitivity** 📖: Calibrated thresholds for the default embedding model (`BAAI/bge-large-en-v1.5`) are written to `.env` automatically as a starting point — they are suggestive and you are encouraged to fine-tune them for your data. If you switch to a different embedding model, thresholds will be reset to a permissive `0.4` fallback and will need recalibration. Refer to [the doc](docs/3_RAG_performance_analysis.md) for details.

### 2. Build and start

Run:
```bash
docker compose up -d --build
```



### 3. Download the embedding model

If you ran `bin/setup.sh` in step 1, the model was already downloaded. If you configured manually or need to re-download:

```bash
bash bin/download-model.sh
```

This is a one-time download (~1.3 GB). The model is stored in `data/cache/huggingface/` and reused across container restarts. See [docs/7_embedding_model.md](docs/7_embedding_model.md) for details on compatible models and how to switch models safely.

> [!IMPORTANT]
> The Docker image must be built (`docker compose build`) before running `download-model.sh`, as the script runs inside the `rag-proxy` image.

### 4. Place the files

Two files are always required:

- A `.po` file containing **untranslated strings** — this is what the system will translate
- At least one RAG context source: a **translation memory** (`.po`) and/or a **glossary** (`.csv`) — either alone is sufficient, both together gives the best results

If you wish to quickly run a demo, running `bash bin/demo_prep.sh` will download all the necessary files. Then you can proceed to [the next step](#5-ingest-the-translation-memory-and-glossary).

If you prefer to place the files manually, follow the steps below:

#### Untranslated strings

Place untranslated `.po` files under `data/translations/input/<langcode>/` (e.g. `data/translations/input/ja/`).

For Drupal core translations, a `.po` file containing only untranslated strings can be generated from a Drupal instance using the following command (after importing currently available translations):

`drush locale:export {langcode} --types=not-translated > untranslated.po`


#### Translation memory and glossary

RAG context files must be placed under `data/tm_source/<langcode>/` (e.g. `data/tm_source/ja/`). At least one of the following is required; providing both gives the best translation quality:

**Translation memory** — a `.po` file with translated strings:
  - For Drupal core translations, download the relevant `.po` file from https://ftp.drupal.org/files/translations/all/drupal/ (this is more resource-friendly than using the export feature on l.d.o 😉)

**Glossary** — a `.csv` file mapping English source terms to their translations in the target language:
- Required columns:
  - **source**: original string e.g. `Node`
  - **target**: translation e.g. `ノード`

> [!TIP]
> Don't have a glossary yet? The project includes a tool that extracts term candidates from your translation memory and highlights the most frequent translations. See [docs/4_glossary_extraction.md](docs/4_glossary_extraction.md).

#### Custom system prompts (Optional)
You can provide project-specific translation instructions by placing a custom system prompt file. 

- **Location**: `config/prompts/custom/`
- **Naming Convention**: `{langcode}.md` (for example, `nl.md`, `es.md` etc).
- **Effect**: If present, this markdown file will be used as the base expertise instruction for the LLM when translating into the target language, overriding the default prompts provided with the system.

### 5. Ingest the translation memory and glossary

In the terminal, run the ingestion command:

```bash
bash bin/ingest.sh
```

The script checks that the Docker stack is healthy, then lets you select the ingestion mode (full, glossary-only, or TM-only) and target language interactively.

To verify what was ingested into the database:

```bash
docker compose exec toolbox python3 /app/src/check_db.py
```

### 6. Translate!

Finally, run the following command to start the translation process:

```bash
bash bin/translate.sh
```

The dry run option will send no API calls to the LLM, but will still generate the output files.

Once the translation is complete, the .po file with the translated strings will be stored in `data/translations/output`.

> [!NOTE]
> For the best translation quality, tune the RAG similarity thresholds after your first run. Default thresholds are permissive — calibrating them to your data and embedding model can significantly improve context retrieval. See [docs/3_RAG_performance_analysis.md](docs/3_RAG_performance_analysis.md) for the procedure.

### Custom Model Configuration (Optional)

You can override the default list of LLM models by providing a custom model configuration file. This is useful when adding providers not covered by the setup wizard, or when customising the model menu labels.

- **Location**: `config/models/custom/`
- **Setup**: Copy `config/models/custom/models.example.json` to `config/models/custom/models.json` and add your model definitions.
- **Effect**: If present, the system will load models from this file instead of `config/models/models.json`. The default `dry-run` model is automatically preserved to ensure testing capability.
- **Model config changes** are picked up automatically — no container restart is needed.

See [docs/8_multi_llm_support.md](docs/8_multi_llm_support.md) for full details on custom provider configuration.



# Documentation

The following documents provide detailed information about the project's technical implementation, logic, as well as features that help improve the quality of the translations:

- [**Architecture & RAG Workflow**](docs/1_architecture.md): An overview of the system's architecture, pipeline (i.e. ingestion and translation), and the role of the RAG Proxy.
- [**Post-Processing Framework**](docs/2_post_processing.md): Details on the extensible post-processing pipeline that supports both default and custom plugins for cleaning and formatting translated strings.
- [**RAG Performance Analysis**](docs/3_RAG_performance_analysis.md): A guide on monitoring RAG performance, interpreting distance metrics, and tuning thresholds for optimal accuracy.
- [**Glossary Extraction & Audit**](docs/4_glossary_extraction.md): Translation consistency can diminish over time. This tool extracts 1–3 word terms from the existing Translation Memory to generate a draft glossary. It identifies the most frequent translations and highlights usage variations, facilitating terminology consistency audits and building a data-driven foundation for a unified user experience.
- [**Translation Evaluation**](docs/5_translation_evaluation.md): Details on how to evaluate the quality of RAG-based translations by comparing two files (one with RAG context and another without) using an LLM as an independent judge.
- [**ChromaDB Admin UI**](docs/6_chromadb_admin.md): A lightweight (~30MB) web interface for visually browsing collections, inspecting documents and metadata, filtering by language, and running ad-hoc similarity searches against the vector database.
- [**Embedding Model Configuration**](docs/7_embedding_model.md): How to download, and switch text embedding models. Includes compatible model list, safety guardrails, and troubleshooting for model mismatch errors.
- [**Multi-LLM Provider Support**](docs/8_multi_llm_support.md): How to connect to different LLM providers, including, but not limited to, Anthropic Claude, Google Gemini, Mistral, OpenAI o-series, Ollama, and any OpenAI-compatible endpoint via the built-in LiteLLM gateway.