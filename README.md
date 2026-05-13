# RAG-LLM Translator: Context-Aware Localisation

The RAG-LLM Translator leverages Large Language Models and a Retrieval-Augmented Generation (RAG) architecture to automate PO file translation while ensuring high accuracy and terminology consistency. It has been generalised to support most PO translation projects, expanding on its initial role as a translation aid for the Drupal community (https://www.drupal.org/project/translation_llm).

The system supports any LLM provider out of the box, via two complementary modes:

- **Direct mode** (default): Connect directly to any OpenAI-compatible endpoint by setting `LLM_BASE_URL` in your `.env` file. Works with amazee.ai, OpenRouter, Ollama, Mistral, and others.
- **Gateway mode** (optional): Run the bundled [LiteLLM](https://github.com/BerriAI/litellm) container to access providers with non-OpenAI APIs — including **Anthropic Claude** and **Google Gemini** — without any code changes. Also handles OpenAI's newer reasoning models (o-series, GPT-5) which require different call parameters.

See [docs/8_multi_llm_support.md](docs/8_multi_llm_support.md) for setup instructions.

# How to use rag-llm-translator

## System Menu (Recommended)

The easiest way to get started is the interactive system menu, which groups all commands by workflow and guides you through each step:

```bash
bash bin/system_menu.sh
```

The menu detects the current state of your environment (missing `.env`, Docker not running, empty ChromaDB) and shows contextual hints. It also displays preparation instructions before running commands that require files to be in place.

## Overview
To use the translator, you need to:
1. **Configure**: Run the setup script to create the `.env` file with your LLM credentials and settings.
2. **Build**: Build the Docker environment.
3. **Prepare the data**: Place untranslated `.po` files and RAG data (TM and glossary) in the data directory.
4. **Ingest**: Populate the vector database with your TM and glossary data.
5. **Translate**: Run the translation script.
6. **Tune RAG thresholds**: Calibrate similarity thresholds for your data and embedding model.

If you prefer to run commands individually, follow the steps below:

## 1. Create the .env file

Run:
```bash
bash bin/initial_setup.sh
```

...and supply the required information as prompted. The script handles configuration of the following settings. When setting it up for the first time, choose the default value for settings marked with '*':
- **LLM**:
  - API credentials
  - URL endpoint
- **Localization**:
  - Target language
  - *Processing batch size
- **Cleanup**:
  - Selection of post-processing plugins (Choose `N` if the target language is not Japanese AND no custom plugins are provided)

> [!NOTE]
> **RAG Sensitivity** 📖: Default thresholds for semantic matching and distance sensitivity are applied automatically during setup. Refer to [the doc](docs/3_RAG_performance_analysis.md) for details on how to fine-tune these values in your `.env` file if needed.

## 2. Build

Run:
```bash
docker compose up -d --build
```



## 3. Place the files

Three files are required to perform the RAG-based translation:

- a .po file containing untranslated strings
- a .po file containing existing translations as translation memory
- a .csv file containing glossary

If you wish to quickly run a demo, running `bash bin/demo_prep.sh` will download all the necessary files. Then you can proceed to [the next step](README.md#5-ingest-the-translation-memory-and-glossary).

If you prefer to place the files manually, follow the steps below:

### Untranslated strings

Place untranslated.po files under `data/translations/input`.

For Drupal core translations, a .po file containing only untranslated strings can be generated from a Drupal instance using the following command (after importing currently available translations):

`drush locale:export {langcode} --types=not-translated > untranslated.po`


### Translation memory and glossary
Although the system still translate without RAG, maximizing the benefits of a RAG-based approach requires a translation memory and glossary. Incorporating these resources is the most effective way to ensure high-quality, consistent output. As such, their ingestion is highly recommended.

**Location**: Save these files under `data/tm_source`. 

**Translation memory**: A .po file with translated strings.
  - For Drupal core translations, download the relevant .po file from https://ftp.drupal.org/files/translations/all/drupal/ (this is more resource-friendly than using the export feature on l.d.o 😉)

**Glossary**: a .csv file containing the original words in English and its translations in the target language
- It must have the following columns:
  - **source**: original strings e.g. `Node`
  - **target**: translations e.g. `ノード`

### Custom system prompts (Optional)
You can provide project-specific translation instructions by placing a custom system prompt file. 

- **Location**: `config/prompts/custom/`
- **Naming Convention**: `{langcode}.md` (for example, `nl.md`, `es.md` etc).
- **Effect**: If present, this markdown file will be used as the base expertise instruction for the LLM when translating into the target language, overriding the default prompts provided with the system.

## 4. Custom Model Configuration (Optional)
You can override the default list of LLM models by providing a custom model configuration file. This is required when using providers other than the default (amazee.ai).

- **Location**: `config/models/custom/`
- **Setup**: Copy `config/models/custom/models.example.json` to `config/models/custom/models.json` and add your model definitions.
- **Effect**: If present, the system will load models from this file instead of `config/models/models.json`. The default `dry-run` model is automatically preserved to ensure testing capability.
- **Model config changes** are picked up automatically — no container restart is needed.


## 5. Ingest the translation memory and glossary

In the terminal, run the ingestion command:

```bash
docker compose exec toolbox python3 /app/src/ingest.py
```
The script identifies the provided glossary/translation memory and ingests them into the vector database.

The presence of collections and items in the database can be verified by executing the following command:

``` bash
docker compose exec toolbox python3 /app/src/check_db.py
```

## 6. Translate!

Finally, run the following command to start the translation process:

```bash
bash bin/translate.sh
```

The dry run option will send no API calls to the LLM, but will still generate the output files.

Once the translation is complete, the .po file with the translated strings will be stored in `data/translations/output`.

> [!NOTE]
> For the best translation quality, tune the RAG similarity thresholds after your first run. Default thresholds are permissive — calibrating them to your data and embedding model can significantly improve context retrieval. See [docs/3_RAG_performance_analysis.md](docs/3_RAG_performance_analysis.md) for the procedure.



# Documentation

The following documents provide detailed information about the project's technical implementation, logic, as well as features that help improve the quality of the translations:

- [**Architecture & RAG Workflow**](docs/1_architecture.md): An overview of the system's architecture, pipeline (i.e. ingestion and translation), and the role of the RAG Proxy.
- [**Post-Processing Framework**](docs/2_post_processing.md): Details on the extensible post-processing pipeline that supports both default and custom plugins for cleaning and formatting translated strings.
- [**RAG Performance Analysis**](docs/3_RAG_performance_analysis.md): A guide on monitoring RAG performance, interpreting distance metrics, and tuning thresholds for optimal accuracy.
- [**Glossary Extraction & Audit**](docs/4_glossary_extraction.md): Translation consistency can diminish over time. This tool extracts 1–3 word terms from the existing Translation Memory to generate a draft glossary. It identifies the most frequent translations and highlights usage variations, facilitating terminology consistency audits and building a data-driven foundation for a unified user experience.
- [**Translation Evaluation**](docs/5_translation_evaluation.md): Details on how to evaluate the quality of RAG-based translations by comparing two files (one with RAG context and another without) using an LLM as an independent judge.
- [**ChromaDB Admin UI**](docs/6_chromadb_admin.md): A lightweight (~30MB) web interface for visually browsing collections, inspecting documents and metadata, filtering by language, and running ad-hoc similarity searches against the vector database.
- [**Embedding Model Configuration**](docs/7_embedding_model.md): How to download, and switch text embedding models. Includes compatible model list, safety guardrails, and troubleshooting for model mismatch errors.
- [**Multi-LLM Provider Support**](docs/8_multi_llm_support.md): How to connect to different LLM providers, including Anthropic Claude, Google Gemini, OpenAI o-series, and any OpenAI-compatible endpoint. Covers both direct mode and the optional LiteLLM gateway.