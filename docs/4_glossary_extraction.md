# Glossary Extraction Guide

The purpose of this script is to restore translation consistency, which often diminishes over time as projects evolve and multiple contributors (or LLM models/versions) participate. This tool helps developers grasp variations in terminology by extracting 1–3 word terms from the Translation Memory and identifying the most frequent "primary" translations. Beyond standardisation, it serves as a diagnostic tool to identify outdated phrasing and provides a data-driven foundation for a formal project glossary, ensuring a high-quality, unified user experience.

## Usage
Run this script to audit your database consistency or to create a baseline for a new `glossary.csv`:

**Command:**
```bash
docker compose exec toolbox python3 /app/src/extract_glossary_from_db.py
```
The script identifies candidate glossary terms by analyzing the translation memory stored in the `app_tm` collection within ChromaDB.

## Overview
As project translations are performed over many years, terminology consistency often diminishes. For example, variations might occur between **"ブラウザ"** and **"ブラウザー"** for "Browser."

The `extract_glossary_from_db.py` script addresses this by generating a **draft glossary** from the existing **Translation Memory (TM)** stored in ChromaDB. 

### Key Features
* **Term Frequency:** Identifies how often specific translation pairs appear across the entire database.
* **Variation Detection:** Specifically flags English terms that have multiple translations, showing the "Primary" choice versus "Alternatives."
* **Consistency Scoring:** Calculates a percentage to show how consistently a primary term is used relative to all other variations found.

---

## Mechanics: How it Works

The script processes the database in four distinct phases to ensure the resulting glossary is clean and relevant.

### Phase 1: Identifying Candidates
The script scans the `app_tm` collection in ChromaDB to find potential glossary terms.
* **Selection Criteria:** It targets short strings (1 to 3 words) that are under 50 characters, as these are likely to be "terms" rather than full sentences.
* **Variation Capture:** Every unique source-to-target pair is captured. For instance, if a source term has multiple different translations associated with it, all are stored as candidates for further analysis.
* **Normalisation:** The English source is normalised to lowercase for grouping, ensuring "Browser" and "browser" are treated as the same term.

### Phase 2: Global Frequency Scan
For every candidate term identified, the script performs a frequency count across the full database.
* **Substring Matching:** It checks how often a term (e.g., "Account") appears inside longer translated strings (e.g., "Delete Account").
* **Word Boundaries:** The script uses Regular Expressions (`\b`) to ensure it only counts whole words. This prevents "Node" from being counted inside unrelated strings like "NodeJS."
* **Filtering:** Only terms that appear more than once in the database are retained to avoid noise from one-off translations.

### Phase 3: Pruning Superstrings
To keep the glossary concise, the script removes redundant "long" terms if a shorter "base" term already covers the translation logic.
* **Logic:** If the glossary contains **"Action" → "アクション"**, and it also finds **"Action ID" → "アクションID"**, the latter is pruned.
* **Goal:** This prevents the glossary from being cluttered with compound terms that follow the same rules as their individual parts.
**Note:** Superstrings can be added manually to the final version of the glossary if required.

### Phase 4: Data Aggregation & CSV Composition
The surviving terms are aggregated and exported to `/app/data/rag-analysis/db_derived_glossary.csv`.

**The CSV contains the following columns:**

| Column | Description | Example |
| :--- | :--- | :--- |
| **Source** | The English term (primary variation). | `Browser` |
| **Target** | The most frequent Japanese translation (the "Winner"). | `ブラウザー` |
| **Total Occurrences** | The count for this specific translation. | `42` |
| **Consistency** | Percentage of usage compared to all other variations of this term. | `89.0%` |
| **Alternatives** | Other translations found, with their specific occurrence counts. | `ブラウザ (5); 閲覧ソフト (1)` |

---

