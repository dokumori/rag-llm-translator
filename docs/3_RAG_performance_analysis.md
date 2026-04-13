# Translation Quality Analysis

To ensure high-quality translations, it is necessary to monitor the performance of the Retrieval-Augmented Generation (RAG) system. The script `analyse_logs.py` is provided to evaluate system accuracy and the relevance of retrieved data.

## Notes on Cost vs Quality

Translations are processed in batches (default: 15) to balance cost and quality. This leverages shared context and reduces token usage. Smaller batches may improve quality but increase costs; larger batches reduce costs but may impact results.

## Running the Analysis

The RAG proxy logs all activities, including the distance scores for every retrieved segment. These logs are parsed to generate statistical reports and CSV exports.

## Prerequisite

The following conditions must be met before an analysis is conducted:

1. **Verify Database**: Run `check_db.py` to ensure the vector database is populated:
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
--- 📏 Distance Statistics ---

▸ All Potential Matches (accepted + rejected)
Type       Count   Mean       95%        Min        25%        50%        75%        Max
Glossary   1301    0.310153   0.420555   -0.000001  0.278032   0.335388   0.377384   0.477361
TM         1301    0.237747   0.355981   -0.000001  0.186667   0.243500   0.293970   0.442293

▸ Accepted Matches Only
Type       Count   Mean       95%        Min        25%        50%        75%        Max
Glossary   483     0.233000   0.358000   -0.000001  0.198000   0.240000   0.280000   0.400000
TM         682     0.187000   0.270000   -0.000001  0.150000   0.190000   0.230000   0.350000

--- 💡 Recommended Settings ---
Based on 1165 accepted matches:
- GLOSSARY_THRESHOLD:  0.36
- TM_THRESHOLD:        0.27
- Explanation:
  • Thresholds: Calculated using the 95th percentile of valid matches, capped at max observed + 0.05.
```

### Applying Threshold Adjustments

To apply these recommendations, copy the `GLOSSARY_THRESHOLD` and `TM_THRESHOLD` values directly from the script output into your `.env` configuration.

> [!IMPORTANT]
> The recommended values are based on the matches currently being accepted. If you change the underlying strict distance threshold (`RAG_STRICT_DISTANCE_THRESHOLD`), you must **recreate the proxy container**, **execute a fresh translation**, and then re-run the analysis to see the updated recommendations.

### How it Works (Technical Logic)
The script uses a **95th Percentile** approach to identify the boundary where 95% of your previously "Accepted" matches sit. This boundary becomes the new recommendation, ensuring the system adapts to the empirical quality of your specific dataset while excluding extreme outliers. As a safety constraint, recommendations are never allowed to exceed `Maximum Observed Distance + 0.05`.

For a deeper breakdown of the values shown in the report, refer to the [Metric Definitions](#metric-definitions) section.

---

## Distance Metrics and Baseline Performance

### Understanding Cosine Distance
The system calculates **Cosine Distance** (ranging from 0.0 to 1.0) to measure the semantic gap between the source text and the retrieved segment. 



> [!IMPORTANT]
> **Model-Specific Thresholds:** The absolute distance numbers below (e.g., 0.20 – 0.30) are explicitly calibrated to the baseline performance of the **`BAAI/bge-large-en-v1.5`** embedding model. Different models cluster semantic relationships differently (anisotropy). If you swap out this embedding model, you cannot rely on these specific numbers and must recalculate your operational threshold zones from scratch.
> 
> **Data Dependency:** Furthermore, these zones are based on a [Drupal Core translation dataset](https://ftp.drupal.org/files/translations/all/drupal/drupal-11.0.6.ja.po) and a sample [glossary](https://www.drupal.org/files/issues/2026-01-22/glossary.csv). While the target language being translated into is irrelevant to RAG distance (distance is measured exclusively between two English strings), the optimal threshold will still fluctuate depending on the quality, quantity, and vocabulary density of your specific domain dataset.

* **High-Confidence (0.00 – 0.20):** Near-exact matches or high-frequency technical terms (e.g., 'Media Field' vs 'Field').
    * **Action:** Matches are typically accepted via lexical guardrails.
* **Optimal Context (0.20 – 0.30):** Semantically similar but with synonyms or phrasing variations (e.g., 'Revision Log' vs 'Revision').
    * **Action:** Primary operational range for RAG-driven assistance.
* **The Shadow Zone (0.30 – 0.45):** Conceptually related but linguistically distinct; prone to causing hallucinations.
    * **Action:** Distance Rejected by default thresholds.
* **Noise Zone (> 0.45):** New or unique content unrelated to existing data.
    * **Action:** Rejected; LLM relies on internal knowledge.

### Tracking Your Baseline

To track the effectiveness of your RAG setup over time, the `analyse.sh` script will automatically generate a timestamped markdown report and CSV data dumps during each run.

* **Analysis Reports (`rag-performance-report_*.md`)**: A full, human-friendly summary of the Performance Summary, Acceptance Rate, distance stats, and newly recommended thresholds.
* **Match Exports (`matches_*.csv` / `rejected_matches_*.csv`)**: The raw string match data used to generate the report, useful for manual tuning.

You will find all historical reports in your `data/rag-analysis/` directory.

> [!TIP]
> **Total Attempts** refers to the number of unique source strings processed across all batches (each batch contains up to 15 strings by default). **Precision** measures how often vector matches were linguistically relevant, while **Coverage** measures how much of your content received RAG assistance.

### Metric Definitions

The analysis report is divided into several sections, defined as follows:

#### 1. Performance Summary
* **Total Attempts**: The number of unique source strings processed across all translation batches.
* **Accepted Matches**: Matches that passed both the Distance Threshold and the Linguistic Guardrails.
* **Guardrail Blocked**: Matches that were within the distance threshold but were rejected because they shared no lexical words/stems with the source.
* **Distance Rejected**: Matches where the vector distance exceeded the mathematical threshold (`TM_THRESHOLD` or `GLOSSARY_THRESHOLD`).
* **Precision (Linguistic)**: The percentage of vector-similar matches that were successfully accepted (i.e., `Accepted / (Accepted + Guardrail Blocked)`).
* **Coverage (RAG)**: The percentage of total unique source strings that received RAG assistance.

#### 2. Acceptance Rate
* **Accepted**: The total count of all glossary and TM matches that will be sent to the LLM.
* **Rejected**: The total count of matches excluded due to distance or guardrails.

#### 3. Distance Statistics
Comparing these tables helps identify **Signal Drift**—precision loss occurring as source content evolves or the database becomes semantically "crowded."

* **All Potential Matches (accepted + rejected)**: Measures overall "fit"; high distances indicate source content is unrelated to the database.
* **Accepted Matches Only**: Matches passing all guardrails. 
    * **95% Column**: Informs recommended thresholds via the "95th Percentile" logic.
    * **Mean Column**: Represents **"Average Match Closeness."** Lower values are better. A significant increase over time signals data drift or a "crowded" database (increasing false-friend risks).

#### 4. Synonym Guardrail Analysis
* **Total unique RAG matches**: The total number of unique string-to-context pairs retrieved.
* **Matches that shared zero linguistic words/stems**: The specific count of retrieved matches that triggered the Synonym Guardrail check because they share no lexical overlap with the source.

### The Strict Distance Threshold (Synonym Guardrail)
A strict threshold (`RAG_STRICT_DISTANCE_THRESHOLD`, located in your `.env` file; default `0.15`) overrides the Linguistic Precision Check. Strings with zero matching words are normally rejected unless their cosine distance is below this "semantic synonym" floor.

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

### Reviewing the Exported Data (CSV Artifacts)

To verify the accuracy of the automated recommendations or to perform deep-dive troubleshooting, you should inspect the detailed datasets exported to `data/rag-analysis/` during each run:

**A. Matches (`matches_*.csv`)**
* Contains strings (`untranslated_string`) where the system successfully identified a high-quality match in the RAG repository (`rag_context`).
* **Use case**: This file was reviewed to verify context accuracy. Initially, false-friends were included in this list, which led to the introduction of the linguistic guardrail.

**B. Rejected Matches (`rejected_matches_*.csv`)**
* Lists strings (`untranslated_string`) where the system could not identify a sufficiently close match within defined thresholds.
* **Use case**: This file was reviewed to ensure the threshold was not too strict. Review the `dist` column here to calibrate your strict threshold.
---

# RAG Threshold Calibration and Maintenance

Periodic analysis ensures RAG accuracy as your database grows. 

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

* **Precision Risk**: Dense databases increase the risk of "False Friends" (e.g., "Delete" vs "Delegate"). Strict thresholds maintain precision.
* **Density Benefit**: Increased volume improves the probability of exact matches, shifting distribution toward the "Distance Floor" (approx. 0.18–0.22 for the BGE-Large-EN model).

## 3. Interpreting Analysis Numbers
The following logic determines if threshold adjustments are required:

| Observation | Action |
| :--- | :--- |
| Matches accepted at high distances (e.g., 0.38) are incorrect. | **Decrease** threshold (e.g., 0.38 → 0.36). |
| Correct matches are rejected at low distances (e.g., 0.34). | **Increase** threshold (e.g., 0.34 → 0.36). |
| The mean distance of accepted matches approaches the threshold. | Tighten thresholds to ensure data quality. |

### The Core Principle
**False positives (incorrect data) are more detrimental than false negatives (no data).** In the absence of RAG data, the LLM safely relies on internal knowledge. Incorrect RAG context can lead to corrupted translation outputs. Therefore, strict thresholds must be prioritised whenever uncertainty exists.
