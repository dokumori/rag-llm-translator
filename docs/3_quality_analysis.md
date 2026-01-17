# Translation Quality Analysis

To ensure high-quality translations, it is important to monitor the performance of the Retrieval-Augmented Generation (RAG) system. The script `analyse_logs.py` is provided to evaluate the system's accuracy and the relevance of the retrieved data.

## Notes on cost vs quality

To optimize cost-efficiency of the translation process while maintaining the consistency and quality of the translated strings, strings are processed in batches. For the initial version of this PoC, a batch size of 15 has been implemented, providing a balance that leverages shared context and reduces token usage without a substantial impact on results.

## Running the Analysis
The RAG proxy logs its activities, including the distance scores for every retrieved segment. You can parse these logs to generate statistical reports and CSV exports.

## Prerequisite

Before running the analysis, you must:
1. Make sure the vector database is populated. You can check by running:
   ```bash
   docker compose exec toolbox python3 /app/src/check_db.py
   ```
2. If the vecotr DB is dempty, ingest the translation memory and glossary. For details, see [4. Ingest the translation memory and glossary](../README.md#4-ingest-the-translation-memory-and-glossary).
  - Ensure both `drupal_tm` and `drupal_glossary` exist.
  If the count is zero or significantly lower than expected, the ingestion process (`ingest.py`) must be run again, or check if the source isn't corrupt.

3. Run the translation process (dry-run is sufficient) so you will have the logs to analyse. For details, see [5. Run the translation process](../README.md#5-translate).
4. Analyse the logs.
  ```bash
  bash bin/analyse.sh
  ```

## Distance Metrics

### Understanding Cosine Distance
The script calculates the **Cosine Distance** between your input text and the retrieved Translation Memory (TM) entries. Understanding this metric is key to judging the quality of your vector database.

* **Metric Used:** Cosine Distance (0 to 1).
* **Interpretation:**
    * **Near 0.0:** The input is almost identical to a known existing translation. This is an excellent match.
    * **0.3 - 0.4:** The input is semantically similar but not identical. The context provided to the LLM is likely relevant.
    * **Above 0.5:** The input is likely unrelated or new. The retrieval system struggled to find close matches.

### Baseline Metrics for Japanese Translations
For the initial PoC, the vector database was populated with the latest available [Japanese translations for Drupal Core](https://ftp.drupal.org/files/translations/all/drupal/drupal-11.0.6.ja.po) as of December 2025 and glossary (TODO: add a link to the glossary). When running the analysis against a batch of untranslated strings extracted from Drupal 11.0.6, the following baseline performance was observed:

| Type | Count | Mean Distance | Min | Max |
| :--- | :--- | :--- | :--- | :--- |
| **Glossary** | 2590 | **0.247** | 0.150 | 0.311 |
| **TM** | 2590 | **0.227** | 0.131 | 0.286 |

**Analysis of these results:**
* **High Relevance:** The mean distances (approx. 0.23 - 0.25) are very low. This indicates that the untranslated strings in Drupal are highly consistent with existing translations. The RAG system is successfully finding highly relevant context for almost every query.
* **Acceptance Rate:** Out of **5180** potential matches found, the system accepted **2350** (approx. 45%) as high-quality context to send to the LLM. This shows the filtering logic is working effectively to exclude "noise" while retaining useful references.

### How the analysis was made
The script exports detailed data to `/app/data/rag-analysis` for manual review.

**A. Matches (`matches.csv`)**
  * This file contains source strings where the system found a good match in the TM.
  * Use case: Review this to verify that the retrieved context was actually helpful and that the LLM is not blindly copying outdated translations.

**B. Near Misses (`near_misses.csv`)**
  * This file contains source strings where the system failed to find a close match.
  * Use case: These represent "new" content. Such translations should be reviewed more carefully, as the LLM relies solely on its training data without specific Drupal context.

# Maintenance: RAG Threshold Tuning

As the Translation Memory (TM) and Glossary grow, the density of the vector database changes. Periodic analysis is required to ensure the Retrieval-Augmented Generation (RAG) system remains a helpful assistant rather than a source of "hallucinated" translations.

## 1. When to Perform Analysis

Tuning is not a daily task but should be triggered by specific events:

* **Significant Data Injection:** After importing large batches of `.po` files (TM) or significantly updating the Glossary CSV.
* **Quality Drift:** When incorrect context suggestions are reported (e.g., using a translation for "Save" meant for a file when the context is a node).
* **Model Upgrades:** Upon switching the underlying embedding model (e.g., from `multilingual-e5-large` to a newer version), as different models possess different distance characteristics.
* **Project Milestones:** After approximately every 5,000 newly translated strings.

## 2. Impact of Data Growth

As datasets grow, the "Vector Space" becomes more crowded. This impacts retrieval in two ways:

* **The Precision Risk:** In a dense database, semantically distinct terms (e.g., "Delete Account" and "Delegate Account") may appear close in vector distance (e.g., 0.21). Without a strict threshold, incorrect matches may be accepted by the system.
* **The Benefit of Density:** Conversely, increased data volume raises the probability of exact matches. More items will appear near the "Distance Floor" (approx. 0.13–0.15 for this specific model), improving overall consistency.

## 3. Interpreting Analysis Numbers

Analysis reports should be reviewed using the following logic to determine if `TM_THRESHOLD` and `GLOSSARY_THRESHOLD` require adjustment.

### Identifying the Semantic Boundary
The threshold defines the limit where two strings share the same meaning. For the `multilingual-e5-large` model, critical metrics include:

| Metric | Observation | Action |
| :--- | :--- | :--- |
| **High-Distance Successes** | Matches accepted at 0.24 that are incorrect or misleading. | **Decrease** threshold (e.g., 0.25 → 0.23). |
| **Low-Distance Rejections** | Misses rejected at 0.26 that are actually correct and helpful. | **Increase** threshold (e.g., 0.25 → 0.27). |
| **Mean vs. Max** | The mean distance of accepted matches approaches the threshold. | Data quality may be degrading; tighter thresholds are recommended. |

### The Core Principle of RAG Tuning
**False Positives (bad data) are more detrimental than False Negatives (no data).** This represents a "garbage in, garbage out" scenario, where the accumulation of low-quality or incorrect data within the vector database significantly degrades the reliability of the entire system.

If the RAG system provides an incorrect translation, the LLM will often trust it, resulting in a corrupted PO file. If the RAG system provides no data, the LLM relies on internal knowledge, which is generally safer. Therefore, strict thresholds (lower numbers) should be prioritized when uncertainty exists.
