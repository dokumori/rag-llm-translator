# What is this?

This is a PoC for https://www.drupal.org/project/translation_llm. It is a tool that uses LLMs to semi-automate the translation process of Drupal codebase strings, while also ensuring consistency and accuracy through a RAG-based architecture.
Human intervention is required for the quality check and approval for the strings to be accepted. The full automation of the translation process, therefore, is outside of the scope of this project.

This PoC currently supports AI providers that are compliant with the OpenAI API. 

# How to use the llm translator

- **Configure and build**: Run the setup script to create the .env file, then build the Docker environment.
- **Prepare**: Place untranslated `.po` files and RAG data (TM and glossary) in the data directory.
- **Ingest**: Populate the vector database with your RAG data.
- **Translate**: Run the translation script to process your files.

It also comes with the tools to analyse the quality of the translations and extract glossary terms.

Follow the instructions below to set up the environment and run the translation process:

## 1. Create the .env file

Run:
`execute bin/initial_setup.sh`

...and supply the **API key** and the **endpoint URL**. (If you don't have an API key for amazee.ai, you can get a 30-day free trial from [here](https://amazee.ai/trial).

This script also takes care of creation of directories, setting permissions etc.

## 2. Build

Run:
`docker compose build && docker compose up -d`

## 3. Place the files

Running the command `bin/demo.sh` will place all the necessary files to run a demo. If you want to place the files manually, follow the steps below:

### Untranslated strings
You can generate a .po file that only contains untranslated strings from a working Drupal instance using the following command, after importing translation strings that are currently available:

`drush locale:export {langcode} --types=not-translated > untranslated.po`

Place untranslated.po file under `data/translations/input`.

### Translation memory and glossary
While the system works perfectly fine without a translation memory and glossary, it defeats the purpose of the RAG-based approach. For maintaining consistency and quality of the translation, it is highly recommended that you ingest them. 

**Location**: Save these files under `data/tm_source`. 

**Translation memory**: A .po file with translated strings.
  - You can download it from https://ftp.drupal.org/files/translations/all/drupal/ (this is more resource-friendly than using the export feature on l.d.o ;) )

**Glossary**: a .csv file containing the original words in English and its translations in the target language
- Name it as `glossary.csv`.
- It must have the following columns:
  - **source**: original strings e.g. `Node`
  - **target**: translations e.g. `ノード`
- 

## 4. Ingest the translation memory and glossary

Open another terminal and run `docker compose exec toolbox python3 /app/src/ingest.py`. It may take a while to be ready. When you see the following messages, you are good to go:

```
rag-proxy  | ⏳ Loading Embedding Model...
rag-proxy  | ✅ Embedding Model Loaded
rag-proxy  |  * Serving Flask app 'app'
rag-proxy  |  * Debug mode: off
rag-proxy  | WARNING: This is a development server. Do not use it in a production deployment. Use a production WSGI server instead.
rag-proxy  |  * Running on all addresses (0.0.0.0)
rag-proxy  |  * Running on http://127.0.0.1:5000
rag-proxy  |  * Running on http://172.20.0.3:5000
rag-proxy  | Press CTRL+C to quit
```

By running the following command, you can check whether the collections and the items are present in the DB:

``` bash
docker compose exec toolbox python3 /app/src/check_db.py
```

Then in the other window (or press ctrl+c, then), run the following command to ingest the translation memory and glossary:
`docker compose exec toolbox python3 /app/src/ingest.py`

## 5. Translate!

Finally, run the following command to translate the untranslates strings:
`bash bin/translate.sh`

Note: This process includes a post-processing step to fix spacing around Drupal variables (e.g., %user) for better Japanese typography. See [Post-Processing Logic](docs/2_post_processing.md) for more details.


### IMPORTANT: Be modest with the use of the LLM resources provided by amazee.ai

Please refrain from running processes that are unnecessary / irrelevant to the goal of this project. Abusing the LLM resources provided by amazee.ai may result in the suspension of your access to the service.

# Documentation

The following documents provide detailed information about the project's technical implementation, logic and other features that help improve the quality of the translations:

- [**Architecture & RAG Workflow**](docs/1_architecture.md): An overview of the system's three-stage pipeline (Ingestion, Translation, Post-Processing) and the role of the RAG Proxy.
- [**Post-Processing Logic**](docs/2_post_processing.md): Details on the regex-based script used to ensure correct spacing for Drupal variables in Japanese translations.
- [**Translation Quality Analysis**](docs/3_quality_analysis.md): A guide on monitoring RAG performance, interpreting distance metrics, and tuning thresholds for optimal accuracy.
- [**Glossary Extraction & Audit**](docs/4_glossary_extraction.md): Translation consistency can diminish as the time goes by. This tool extracts 1–3 word terms from the existing Translation Memory to generate a draft glossary. It identifies the most frequent translations and highlights usage variations, allowing you to audit terminology consistency and build a data-driven foundation for a unified user experience.
