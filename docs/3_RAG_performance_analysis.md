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
3. **Clear the logs from previous runs**: If you have already run the translation multiple times, you want to clear the logs first. The `analyse.sh` script will prompt you to automatically do this at the end of its run. 
   *(Manual Fallback: If you skipped the prompt or need to force a reset before starting, you can run `docker compose up -d --force-recreate rag-proxy`)*
4. **Generate Logs**: Execute the translation process (a dry-run is sufficient) to generate logs for analysis. Refer to [5. Run the translation process](../README.md#5-translate).
5. **Execute Analysis**:
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
- glossary_threshold: 0.36
- tm_threshold: 0.27
- Explanation:
  • Thresholds: Calculated using the 95th percentile of valid matches, capped at max observed + 0.05.

--- 🩺 Diagnostics ---
Average Match Closeness: 0.15 (range: 0.0–1.0, lower = tighter matches)
```

### Applying Threshold Adjustments

> [!IMPORTANT]
> Changing the strict distance threshold (`RAG_STRICT_DISTANCE_THRESHOLD`) affects the resulting **recommended** `glossary` and `tm` thresholds. If you adjust the strict distance threshold, you must **recreate the proxy container, execute a translation (to generate fresh logs)**, and then re-run the analysis to see the updated recommendations.

Map the recommended values to the `.env` configuration as follows:

| Recommended Value | .env Variable | Action |
| :--- | :--- | :--- |
| `glossary_threshold` | `GLOSSARY_THRESHOLD` | Copy value directly. |
| `tm_threshold` | `TM_THRESHOLD` | Copy value directly. |

### How it Works
The script applies a **95th Percentile** approach to determine thresholds. By analysing the distance distribution of matches previously accepted, it identifies the boundary where 95% of valid matches sit, effectively excluding extreme outliers. 

* **Thresholds (`glossary`, `tm`)**: These are calculated as the 95th percentile of accepted distances. As a safety constraint, the recommendation is hard-capped to never exceed `Maximum Observed Distance + 0.05`.

The script also reports a read-only diagnostic:

* **Average Match Closeness**: The mean cosine distance across all accepted matches. A lower value indicates that your data is producing consistently tight, high-confidence matches. If this value increases over time, it may indicate that the vector database has grown crowded or that the source content has drifted from the training data.

After the threshold values are set, your RAG-LLM translator should be well-tuned and ready to use. To learn more about how these recommendations are made, refer to the explanations below.

---

## Distance Metrics and Baseline Performance

### Understanding Cosine Distance
The system calculates **Cosine Distance** (ranging from 0.0 to 1.0) to measure the semantic gap between the source text and the retrieved segment. 



> **Note:** The following interpretation is based on baseline performance using [Japanese translations for Drupal Core](https://ftp.drupal.org/files/translations/all/drupal/drupal-11.0.6.ja.po) and a sample [glossary](https://www.drupal.org/files/issues/2026-01-22/glossary.csv) prepared via `demo_prep.sh`. **These zones are data-dependent;** they may shift significantly depending on the datasets or the underlying embedding model utilised.

* **High-Confidence (0.00 – 0.20):** These represent near-exact matches or high-frequency technical terms. (e.g., 'Media Field' vs 'Field' at 0.179)
    * **Action:** Matches are typically accepted if they pass the lexical word-overlap guardrail.
* **Optimal Context (0.20 – 0.30):** The input is semantically similar but may contain synonyms or slight phrasing variations (e.g., 'Revision Log' vs 'Revision' at 0.205).
    * **Action:** This is the primary operational range for RAG-driven LLM assistance.
* **The Shadow Zone (0.30 – 0.45):** These matches are conceptually related but often linguistically distinct; they are prone to causing "hallucinations" in the translation output.
    * **Action:** To prevent inaccurate context, these are currently **Distance Rejected** by project thresholds.
* **Noise Zone (> 0.45):** The input is likely new, unique, or unrelated to the existing dataset.
    * **Action:** No matches are considered; the LLM relies entirely on its internal training data.

### Tracking Your Baseline

To track the effectiveness of your RAG setup over time, the `analyse.sh` script will automatically generate a timestamped markdown report and CSV data dumps during each run.

* **Analysis Reports (`rag-performance-report_*.md`)**: A full, human-friendly summary of distance stats, newly recommended thresholds, and the Acceptance Rate/Coverage table.
* **Match Exports (`matches_*.csv` / `rejected_matches_*.csv`)**: The raw string match data used to generate the report, useful for manual tuning.

You will find all historical reports in your `data/rag-analysis/` directory.

> [!TIP]
> **Total Attempts** refers to the number of unique source strings processed across all batches (each batch contains up to 15 strings by default). **Precision** measures how often vector matches were linguistically relevant, while **Coverage** measures how much of your content received RAG assistance.

### Metric Definitions
* **Total Attempts**: The number of unique source strings processed across all translation batches.
* **Accepted Matches**: Matches passing both Distance Threshold and Linguistic Guardrails.
* **Guardrail Blocked**: Matches within distance threshold but rejected for lacking shared words (e.g., 'Crop ID' vs 'Identification').
* **Distance Rejected**: Strings where no match was found within the mathematical threshold.
* **Precision (Linguistic)**: The percentage of vector-similar matches that were linguistically relevant.
* **Coverage (RAG)**: The percentage of total strings that received RAG assistance.
* **Total unique RAG matches**: The number of unique string-to-context pairs retrieved from the vector database.
* **Matches that shared zero linguistic words/stems**: The number of retrieved matches that triggered the Synoynm Guardrail because they share no lexical overlap with the source string.

### The Strict Distance Threshold (Synonym Guardrail)
The system utilises a strict distance threshold (`RAG_STRICT_DISTANCE_THRESHOLD`, located in your `.env` file; base default `0.15`) as an override for the Linguistic Precision Check. When two strings have zero matching words, they are normally rejected. However, if the cosine distance is extremely low (below this strict threshold), the system accepts it as a pure semantic synonym.

**Important Note:** Unlike the TM and Glossary thresholds which adapt to the empirical distribution via the 95th Percentile rule, `RAG_STRICT_DISTANCE_THRESHOLD` is a constant calibration value. It represents a conservative, empirical "floor" tuned specifically for **English software and Drupal UI strings** using the `BAAI/bge-large-en-v1.5` model. Because it depends on how the embedding model clusters terminology within a specific semantic domain, users translating vastly different domains (e.g., medical texts, legal documents) may need to tweak this value manually in `.env` by observing the distance of rejected synonyms in `rejected_matches_*.csv`.

## 2. Manual Tuning Workflow (Calibrating Synonyms)

While the script automatically recommends `TM` and `Glossary` thresholds, the **Strict Distance Threshold** requires occasional human verification. If you feel the system is missing too many obvious synonyms, or being too risky with different meanings, follow this "Borderline Case Review" approach:

### The Borderline Case Review
1. **Run the Analysis**: Execute `bash bin/analyse.sh`.
2. **Scan the Terminal Results**: Review the `Synonym Guardrail Analysis` block. If the "Borderline" examples (which sit just above your current threshold) look like correct synonyms, your threshold might be too strict.
3. **Filter the CSV**: Open your latest `data/rag-analysis/rejected_matches_*.csv` and apply these filters:
   - `no_shared_words`: **TRUE**
   - `dist`: **Between 0.05 and 0.15** (The "Critical Zone")
4. **Make the Call**:
   - **Scenario A (Too Strict)**: You see many perfect synonyms (e.g., "Add" vs "Create") being rejected. Check the `dist` value of these rejected pairs. For example, if the `dist` is `0.15` while your current strict threshold is set to `0.12`, you may want to increase `RAG_STRICT_DISTANCE_THRESHOLD` to `0.15` so they get accepted.
   - **Scenario B (Too Loose)**: You see "False Friends" (e.g., "Send" vs "Submit" — similar, but different UI actions) appearing in the borderline bucket. If you loosen the threshold to encompass their `dist` value, they will be accepted! **Action**: Decide to keep the threshold strict or decrease it below their `dist` value to ensure they remain rejected.
5. **Apply the Change**: Update `RAG_STRICT_DISTANCE_THRESHOLD` in your `.env` file. To ensure the new threshold is loaded by the proxy, and to clear the logs from the previous run, manually recreate the container:
   ```bash
   docker compose up -d --force-recreate rag-proxy
   ```
6. **Generate Fresh Logs**: Execute the translation process again (a dry-run is sufficient). This is necessary because the analysis script calculates recommendations based on the "Accepted" decisions recorded in the fresh logs.
7. **Re-run the Analysis**: Run `bash bin/analyse.sh` again to ensure the change had the desired effect on the borderline cases and to see the updated **recommended** `TM` and `Glossary` thresholds. At the end of the script, type `y` to purge the logs so you are ready for future translation batches.
8. **Update Other Thresholds**: Manually copy the newly recommended `GLOSSARY_THRESHOLD` and `TM_THRESHOLD` values into your `.env` file.

### Priority: Safety vs. Coverage
- **Safety First**: If a single dangerous hallucination occurs, prioritize a stricter threshold (lower number). 
- **Coverage First**: If RAG assistance is consistently missing synonyms that you know exist in the DB, loosen the threshold (higher number).

---

### How the Analysis was Conducted
The `analyse.sh` script doesn't only produce recommendations, it also exports detailed datasets to `data/rag-analysis` for manual inspection. The following files provide critical insights:

**A. Matches (`matches_*.csv`)**
* Contains strings (`untranslated_string`) where the system successfully identified a high-quality match in the RAG repository (`rag_context`).
* **Use case**: This file was reviewed to verify context accuracy. Initially, false-friends were included in this list, which led to the introduction of the linguistic guardrail.

**B. Rejected Matches (`rejected_matches_*.csv`)**
* Lists strings (`untranslated_string`) where the system could not identify a sufficiently close match within defined thresholds.
* **Use case**: This file was reviewed to ensure the threshold was not too strict. Review the `dist` column here to calibrate your strict threshold.
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
* **Density Benefit**: Increased data volume raises the probability of exact matches, which will appear near the "Distance Floor" (approx. 0.18–0.22 for the BGE-Large-EN model).

## 3. Interpreting Analysis Numbers
The following logic determines if threshold adjustments are required:

| Observation | Action |
| :--- | :--- |
| Matches accepted at high distances (e.g., 0.38) are incorrect. | **Decrease** threshold (e.g., 0.38 → 0.36). |
| Correct matches are rejected at low distances (e.g., 0.34). | **Increase** threshold (e.g., 0.34 → 0.36). |
| The mean distance of accepted matches approaches the threshold. | Tighten thresholds to ensure data quality. |

### The Core Principle
**False positives (incorrect data) are more detrimental than false negatives (no data).** In the absence of RAG data, the LLM safely relies on internal knowledge. Incorrect RAG context can lead to corrupted translation outputs. Therefore, strict thresholds must be prioritised whenever uncertainty exists.
