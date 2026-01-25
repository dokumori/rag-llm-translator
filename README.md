# RAG-LLM Translator: Context-Aware Localisation

The RAG-LLM Translator leverages Large Language Models and a Retrieval-Augmented Generation (RAG) architecture to automate PO file translation while ensuring high accuracy and terminology consistency. It has been genericised to support most PO translation projects, expanding on its initial role as a translation aid for the Drupal community (https://www.drupal.org/project/translation_llm).

The system is compatible with any AI provider that adheres to the OpenAI API specification.

# How to use rag-llm-translator

## Overview
To use the translator, you need to:
- **Configure and build**: Run the setup script to create the .env file, then build the Docker environment.
- **Prepare the data**: Place untranslated `.po` files and RAG data (TM and glossary) in the data directory. A demo script is available for quick setup.
- **Ingest**: Populate the vector database with your RAG data.

Once these steps are completed, the translation script can be run.

Follow the instructions below to set up the environment and run the translation process:

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
- **RAG Sensitivity**:
  - *Semantic matching thresholds
  - *Distance sensitivity
- **Cleanup**:
  - Selection of post-processing plugins (Choose `N` if the target language is not Japanese AND no custom plugins are provided)

## 2. Build

Run:
```bash
docker compose build && docker compose up -d
```

## 3. Place the files

Three files are required to perform the RAG-based translation:

- a .po file containing untranslated strings
- a .po file containing existing translations as translation memory
- a .csv file containing glossary

If you wish to quickly run a demo, running `bash bin/demo_prep.sh` will download all the necessary files. Then you can proceed to [the next step](README.md#4-ingest-the-translation-memory-and-glossary).

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

## 4. Ingest the translation memory and glossary

In the terminal, run the ingestion command:

```bash
docker compose exec toolbox python3 /app/src/ingest.py
```
The script identifies the provided glossary/translation memory and ingests them into the vector database.

The presence of collections and items in the database can be verified by executing the following command:

``` bash
docker compose exec toolbox python3 /app/src/check_db.py
```

## 5. Translate!

Finally, run the following command to start the translation process:

```bash
bash bin/translate.sh
```

The dry run option will send no API calls to the LLM, but will still generate the output files.

Once the translation is complete, the .po file with the translated strings will be stored in `data/translations/output`.

# Documentation

The following documents provide detailed information about the project's technical implementation, logic, as well as features that help improve the quality of the translations:

- [**Architecture & RAG Workflow**](docs/1_architecture.md): An overview of the system's architecture, pipeline (i.e. ingestion and translation), and the role of the RAG Proxy.
- [**Post-Processing Framework**](docs/2_post_processing.md): Details on the extensible post-processing pipeline that supports both default and custom plugins for cleaning and formatting translated strings.
- [**RAG Performance Analysis**](docs/3_RAG_performance_analysis.md): A guide on monitoring RAG performance, interpreting distance metrics, and tuning thresholds for optimal accuracy.
- [**Glossary Extraction & Audit**](docs/4_glossary_extraction.md): Translation consistency can diminish over time. This tool extracts 1–3 word terms from the existing Translation Memory to generate a draft glossary. It identifies the most frequent translations and highlights usage variations, facilitating terminology consistency audits and building a data-driven foundation for a unified user experience.
