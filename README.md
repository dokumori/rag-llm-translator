# What is this?

This is a PoC for https://www.drupal.org/project/translation_llm. It is a tool that uses LLMs to semi-automate the translation process of Drupal codebase strings, while also ensuring consistency and accuracy through a RAG-based architecture.
Human intervention is required for the quality check and approval. The full automation of the translation process, therefore, is outside of the scope of this project.

Huge thanks to amazee.ai for generously providing their LLM resources for this project ❤️

More information on amazee.ai:
- https://amazee.ai
- https://www.drupal.org/project/ai_provider_amazeeio

# How to use the llm translator

To use the LLM translator, the following steps are required:
- **Configure and build**: Set up the Docker environment and create the `.env` file.
- **Prepare**: Place untranslated `.po` files and RAG data (TM/Glossary) in the data directory.
- **Ingest**: Populate the vector database with your RAG data.
- **Translate**: Run the translation script to process your files.

Detailed instructions for each step are provided below.

## 1. Create the .env file

Run:
`execute bin/initial_setup.sh`

...and supply the API key and the endpoint URL. (At the moment, the API key and the endpoint URL are only shared with the maintainers of https://www.drupal.org/project/translation_llm)

This script also takes care of creation of directories, setting permissions etc.

## 2. Build

Run:
`docker compose build && docker compose up -d`

## 3. Place the files

Running the command `bin/demo.sh` will place all the necessary files to run a demo. If you want to place the files manually, follow the steps below:

**Untranslated strings**: a .po file that only contains untranslated strings. You can generate it from a working Drupal instance using the following command, after importing translation strings that are currently available:

`drush locale:export {langcode} --types=not-translated > untranslated.po`

Place untranslated.po under `data/translations/input`.

**Translation memory and glossary**:
While the system works perfectly fine without a translation memory and glossary, it defeats the purpose of the RAG-based approach. For maintaining consistency and quality of the translation, it is highly recommended to provide them.

- A .po file with translated strings as a translation memory (place it under data/glossary).
  - You can download it from https://ftp.drupal.org/files/translations/all/drupal/ (this is more resource-friendly than using l.d.o ;) )
- A translation dictionary in a .csv format (save as `glossary.csv` under `data/glossary`). It must have the following columns:
  - source: the original string e.g. `Node`
  - target: the translated string e.g. `ノード`

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

Then in the other window (or press ctrl+c, then), run the following command to ingest the translation memory and glossary:
`docker compose exec toolbox python3 /app/src/ingest.py`

## 5. Translate!

Finally, run the following command to translate the untranslates strings:
`bash bin/translate.sh`

Note: This process includes a post-processing step to fix spacing around Drupal variables (e.g., %user) for better Japanese typography. See [Post-Processing Logic](docs/2_post_processing.md) for more details.

### IMPORTANT: Be modest with the use of the LLM resources provided by amazee.ai

Please refrain from running processes that are unnecessary / irrelevant to the goal of this project. Abusing the LLM resources provided by amazee.ai may result in the suspension of your access to the service.

# Documentation

The following documents provide detailed information about the project's technical implementation and logic etc:

- [**Architecture & RAG Workflow**](docs/1_architecture.md): An overview of the system's three-stage pipeline (Ingestion, Translation, Post-Processing) and the role of the RAG Proxy.
- [**Post-Processing Logic**](docs/2_post_processing.md): Details on the regex-based script used to ensure correct spacing for Drupal variables in Japanese translations.
- [**Translation Quality Analysis**](docs/3_quality_analysis.md): A guide on monitoring RAG performance, interpreting distance metrics, and tuning thresholds for optimal accuracy.
- [**Glossary Extraction & Audit**](docs/4_glossary_extraction.md): Over time, translation consistency can diminish as projects grow. This tool extracts 1–3 word terms from the existing Translation Memory to generate a draft glossary. It identifies the most frequent translations and highlights usage variations (e.g., *Browser* vs. *Browsers*), allowing you to audit terminology consistency and build a data-driven foundation for a unified user experience.
