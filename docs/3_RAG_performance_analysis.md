# Translation Quality Analysis

To ensure high-quality translations, it is necessary to monitor the performance of the Retrieval-Augmented Generation (RAG) system. The script `analyse_logs.py` is provided to evaluate system accuracy and the relevance of retrieved data.

## Notes on Cost vs Quality

To optimise the cost-efficiency of the translation process while maintaining the consistency and quality of translated strings, processing occurs in batches. A default batch size of 15 is utilised, providing a balance that leverages shared context and reduces token usage without a substantial impact on results. Smaller batch sizes may improve quality but increase token usage and cost, while larger batch sizes may reduce cost but potentially impact quality.

## Running the Analysis

The RAG proxy logs all activities, including the distance scores for every retrieved segment. These logs are parsed to generate statistical reports and CSV exports.

## Prerequisite

The following conditions must be met before an analysis is conducted:

1. **Verify Vector Database**: Ensure the database is populated by executing:
   ```bash
   docker compose exec toolbox python3 /app/src/check_db.py
   ```
2. **Data Ingestion**: If the vector database is empty, the translation memory and glossary must be ingested. Refer to [4. Ingest the translation memory and glossary](../README.md#4-ingest-the-translation-memory-and-glossary) for details. Both `app_tm` and `app_glossary` must exist. If the count is zero or significantly lower than expected, the ingestion process (`ingest.py`) must be repeated, or the source file must be checked for corruption.
3. **Clear the logs from previous runs**: If you have already run the translation multiple times, you want to clear the logs first. Running the following command is most straight-forward:
   ```bash
   docker compose up -d --force-recreate rag-proxy
   ``` 
3. **Generate Logs**: Execute the translation process (a dry-run is sufficient) to generate logs for analysis. Refer to [5. Run the translation process](../README.md#5-translate).
4. **Execute Analysis**:
   ```bash
   bash bin/analyse.sh
   ```
The next section explains how the result of the analysis can be applied.

## Automated Tuning Recommendations

The `analyse.sh` script concludes with a **Recommended Configuration** block. This feature statistically analyses "Accepted" matches to suggest optimal settings for the `.env` configuration.


### Example Output
```text
--- 💡 Recommended Settings ---
Based on 1023 accepted matches:
- glossary_threshold: 0.25
- tm_threshold: 0.23
- Explanation:
  • Thresholds: Calculated using Mean + 3σ to cover 99.7% of valid matches.

--- 🩺 Diagnostics ---
Average Match Closeness: 0.1525 (range: 0.0–1.0, lower = tighter matches)
```

### How to Apply
Map the recommended values to the `.env` configuration as follows:

| Recommended Value | .env Variable | Action |
| :--- | :--- | :--- |
| `glossary_threshold` | `GLOSSARY_THRESHOLD` | Copy value directly. |
| `tm_threshold` | `TM_THRESHOLD` | Copy value directly. |

### How it Works
The script applies the **3-Sigma Rule** ($\mu + 3\sigma$) to determine thresholds. By analysing the distance distribution of matches previously accepted, it calculates a safe upper limit that covers **99.7%** of valid matches while excluding outliers.

* **Thresholds (`glossary`, `tm`)**: These are calculated as `Mean Distance + (3 * Standard Deviation)`.

The script also reports a read-only diagnostic:

* **Average Match Closeness**: The mean cosine distance across all accepted matches. A lower value indicates that your data is producing consistently tight, high-confidence matches. If this value increases over time, it may indicate that the vector database has grown crowded or that the source content has drifted from the training data.

After the threshold values are set, your RAG-LLM translator should be well-tuned and ready to use. To learn more about how these recommendations are made, refer to the explanations below.

---

## Distance Metrics and Baseline Performance

### Understanding Cosine Distance
The system calculates **Cosine Distance** (ranging from 0.0 to 1.0) to measure the semantic gap between the source text and the retrieved segment. 

> **Note:** The following interpretation is based on baseline performance using [Japanese translations for Drupal Core](https://ftp.drupal.org/files/translations/all/drupal/drupal-11.0.6.ja.po) and a sample [glossary](https://www.drupal.org/files/issues/2026-01-22/glossary.csv) prepared via `demo_prep.sh`. **These zones are data-dependent;** they may shift significantly depending on the datasets or the underlying embedding model utilised.

* **High-Confidence (0.00 – 0.15):** These represent near-exact matches or high-frequency technical terms.
    * **Action:** Matches are typically accepted if they pass the lexical word-overlap guardrail.
* **Optimal Context (0.15 – 0.23):** The input is semantically similar but may contain synonyms or slight phrasing variations (e.g., 'Media Field' vs 'Media item' at 0.145).
    * **Action:** This is the primary operational range for RAG-driven LLM assistance.
* **The Shadow Zone (0.23 – 0.40):** These matches are conceptually related but often linguistically distinct; they are prone to causing "hallucinations" in the translation output.
    * **Action:** To prevent inaccurate context, these are currently **Distance Rejected** by project thresholds (0.23 Glossary / 0.22 TM).
* **Noise Zone (> 0.40):** The input is likely new, unique, or unrelated to the existing dataset.
    * **Action:** No matches are considered; the LLM relies entirely on its internal training data.

### RAG Performance Analysis (Baseline)
When running the analysis against [untranslated strings from Drupal 11.0.6](https://ftp.drupal.org/files/translations/all/drupal/drupal-11.0.6.ja.po), the following baseline was observed:

| Type | Total Attempts | Accepted Matches | Guardrail Blocked | Distance Rejected | Precision (Linguistic) | Coverage (RAG) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Glossary** | 2,590 | 1,030 | 859 | 701 | 54.5% | 39.8% |
| **TM** | 2,590 | 1,030 | 701 | 859 | 59.5% | 39.8% |

### Metric Definitions
* **Total Attempts**: Total lookups performed (Strings processed × Executions).
* **Accepted Matches**: Matches passing both Distance Threshold and Linguistic Guardrails.
* **Guardrail Blocked**: Matches within distance threshold but rejected for lacking shared words (e.g., 'Crop ID' vs 'Identification').
* **Distance Rejected**: Strings where no match was found within the mathematical threshold.
* **Precision (Linguistic)**: The percentage of vector-similar matches that were linguistically relevant.
* **Coverage (RAG)**: The percentage of total strings that received RAG assistance.

### Analysis of Baseline Results:
* **High Semantic Consistency**: The mean distances (approx. 0.23 - 0.25) remain low, indicating that source strings are mathematically consistent with existing data.
* **Linguistic Precision Check**: Relevance is evaluated via an exact word match (lexical intersection). Approximately 40-45% of potential matches were blocked by this guardrail, effectively filtering "false friends".
* **Effective RAG Coverage**: High-confidence RAG assistance is provided for ~40% of all processed strings, ensuring context satisfies both mathematical and lexical safety checks.

---

### How the Analysis was Conducted
The `analyse.sh` script doesn't only produce recommendations, it also exports detailed datasets to `data/rag-analysis` for manual inspection. The following files provide critical insights:

**A. Matches (`matches.csv`)**
* Contains source strings where the system successfully identified a high-quality match in the TM.
* **Use case**: This file was reviewed to verify context accuracy. Initially, false-friends were included in this list, which led to the introduction of the linguistic guardrail.

**B. Near Misses (`near_misses.csv`)**
* Lists source strings where the system could not identify a sufficiently close match within defined thresholds.
* **Use case**: This file was reviewed to ensure the threshold was not too strict.
---

# RAG Threshold Calibration and Maintenance

Periodic analysis is essential to maintain RAG accuracy as the vector database expands.

## 1. Timing for Analysis and Calibration
Calibration is necessitated by specific project events:
* **Initial Project Setup**: Establishes a baseline for new applications to confirm if existing data is relevant to the new codebase.
* **Significant Data Injection**: Large imports or substantial Glossary updates alter the vector space (approximately 5,000+ strings*).
* **Quality Drift**: Analysis is triggered if incorrect context suggestions are observed (e.g., mismatched button labels).
* **Model Upgrades**: Switching embedding models necessitates re-calibration due to differing distance characteristics.
* **Project Milestones**: Re-evaluation is recommended approximately every 5,000 newly translated strings* to maintain precision.

*\*The addition of approximately 5,000 strings is considered a significant injection that increases vector density. This "crowding" of the vector space can reduce the margin between relevant matches and "false friends," necessitating a threshold review to maintain accuracy.*

## 2. Impact of Data Growth
As datasets grow, the "Vector Space" becomes more crowded, impacting retrieval in two ways:

* **Precision Risk**: In dense databases, semantically distinct terms (e.g., "Delete Account" and "Delegate Account") may appear close in vector distance. Strict thresholds are necessary to prevent incorrect matches.
* **Density Benefit**: Increased data volume raises the probability of exact matches, which will appear near the "Distance Floor" (approx. 0.13–0.15 for this model).

## 3. Interpreting Analysis Numbers
The following logic determines if threshold adjustments are required:

| Observation | Action |
| :--- | :--- |
| Matches accepted at high distances (e.g., 0.24) are incorrect. | **Decrease** threshold (e.g., 0.25 → 0.23). |
| Correct matches are rejected at low distances (e.g., 0.26). | **Increase** threshold (e.g., 0.25 → 0.27). |
| The mean distance of accepted matches approaches the threshold. | Tighten thresholds to ensure data quality. |

### The Core Principle
**False positives (incorrect data) are more detrimental than false negatives (no data).** In the absence of RAG data, the LLM safely relies on internal knowledge. Incorrect RAG context can lead to corrupted translation outputs. Therefore, strict thresholds must be prioritised whenever uncertainty exists.
