# What is this for?

This is a PoC for https://www.drupal.org/project/translation_llm. The aim of the project is to simplify the translation process of strings in the Drupal codebase, while maintaining / improving the quality of translation by utilising LLMs in a broad sense.

amazee.ai is generously providing their service for this project. Thank you!

# How to use the llm translator

## 1. Build

Run:
`docker compose build && docker compose up -d`

## 2. Create the .env file

Run:
`execute bin/create_env.sh`

...and supply the API key and the endpoint URL. (At the moment, the API key and the endpoint URL are only shared with the maintainers of https://www.drupal.org/project/translation_llm)

## 3. Place the files in place

**A must-have**: a .po file that only contains untranslated strings. You can generate it from a working Drupal instance using the following command, after importing translation strings that are currently available:

`drush locale:export {langcode} --types=not-translated > untranslated.po`


Place it under `data/translations/input`.

**Nice-to-haves**:

- A .po file with translated strings as a translation memory (place it under data/glossary).
  - You can download it from https://ftp.drupal.org/files/translations/all/drupal/ (this is more resource-friendly than using l.d.o ;) )
- A translation dictionary in a .csv format (save as `glossary.csv` under `data/glossary`). It must have the following columns:
  - source: the original string e.g. `Node`
  - target: the translated string e.g. `ノード`
  - category: e.g. `entity`
  - note: e.g. `content`

## 4. Ingest the translation memory and glossary

Open another terminal and run `docker compose exec toolbox python3 /app/src/ingest.py`. It may take a while to be ready, when you see the following message, you are good to go:

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

Then in the other window (or press ctrl+c, then), run `docker compose exec toolbox python3 /app/src/ingest.py`

## 5. Translate!

Finally, run `bash bin/translate.sh` to translate the untranslates strings

IMPORTANT: Be modest with the use of the LLM provided by amazee.ai, and not run processes that are unnecessary / irrelevant to the goal of this project.

# The architecture

gpt-po-translate intelligently decides 
