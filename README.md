# What is this?

This is a PoC for https://www.drupal.org/node/3558674. Below is a brief description of what this translator does:

- (TBW)

# How to use the translator

## Put the files in place

The filenames don't need to follow the example below:

| File | Location | Description |
|------|----------|-------------|
|en-ja.po|(root)/po/untranslated/|The .po file **without** the translated strings. Export from a working Drupal instance|
|refrerence.po|(root)/tm_source/|The .po file **with** the translations. Used as a reference to improve the quality and consistency of the translation|
|glossary.csv|(root)/tm_source/|The translation dictionary for improving the consistency of the translation|

## Set up the translator

`docker compose up -d --build`

## Check if chromaDB is running

`docker logs chroma-db`

## Import the glossaries and a reference

Import the files to ChromaDB. Every time this command is run, the DB is wiped to accommodate new data.

`docker compose run --rm ingestor`

## Check if the ChromaDB returns relevant records

`docker compose run --rm ingestor python check_rag.py`

## Translate!

Finally, run the script to translate the untranslated strings

`bash scripts/run_job.sh`
