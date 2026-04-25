# RAG Performance Analysis

To ensure high-quality translations, it is necessary to monitor the performance of the Retrieval-Augmented Generation (RAG) system. It is recommended to run this analysis:
- once before executing actual translations, especially if you are using this translator for non-web application strings.
- after ingesting ~5000 new strings (in addition to existing TM/glossary), to avoid performance degradation caused by signal drift.
- when you observe quality degradation in translations.

The script `bin/analyse.sh` evaluates system accuracy and the relevance of retrieved data.

## 1. Quick Start: Analysis Workflow

Follow these steps to generate performance reports and apply automated tuning recommendations.

### Prerequisites
1.  **Verify Database**: Run the following command to ensure the vector database is populated:
    ```bash
    docker compose exec toolbox python3 /app/src/check_db.py
    ```
2.  **Data Ingestion**: If empty, the translation memory and glossary must be prepared and ingested. Refer to [README.md](../README.md#translation-memory-and-glossary) for file placement and [README.md](../README.md#5-ingest-the-translation-memory-and-glossary) for the ingestion process.
3.  **Reset Threshold**: Relax the `GLOSSARY_THRESHOLD` and `TM_THRESHOLD` to `0.4` in `.env` to ensure the test captures a wide range of potential matches and avoid detection of false negatives.
4.  **Clear Logs**: Run the following command to ensure you are starting from a clean state:
    ```bash
    docker compose up -d --force-recreate rag-proxy
    ```

### Running the Analysis
1.  **Generate Logs**: Execute a translation process (a dry-run is sufficient).
2.  **Execute Analysis**:
    ```bash
    bash bin/analyse.sh
    ```

### Output Artifacts
All analysis runs generate timestamped files in `data/rag-analysis/`:
*   `rag-performance-report_*.md`: A human-friendly summary of the metrics and recommended settings.
*   `matches_*.csv`: Detailed records of all successful RAG matches (Accepted).
*   `rejected_matches_*.csv`: Detailed records of all matches that were rejected (due to distance or linguistic guardrails).

### Applying Recommended Settings
The script concludes with a **Recommended Configuration** block. These values (calculated via 95th percentile logic) suggest optimal `GLOSSARY_THRESHOLD` and `TM_THRESHOLD` settings.

1.  **Action**: Copy the values directly into your `.env`.
2.  **Caution**: Automated recommendations are statistical and may leave some "noise" (irrelevant matches) uncaught. It is highly recommended that you verify the boundary cases manually (see Section 2).

---

## 2. Manual Tuning

Automated recommendations provide a statistical baseline, but manual verification is essential to achieve production-grade accuracy.

### 2.1 General Threshold Calibration (The CSV Check)
Before finalizing your `TM_THRESHOLD` and `GLOSSARY_THRESHOLD`, you should manually verify the boundary cases:

**Rejecting False Friends (false positives):**

Inspect `matches_*.csv`.
Sort (descending) by distance and review the matches closest to the upper end of the recommended threshold. If you find irrelevant suggestions are passing through, lower the threshold to tighten the accepted range of distance.

**Accepting Missed Matches (false negatives):**

Inspect `rejected_matches_*.csv`. Sort (ascending) by distance, and filter by 'no_shared_words' = FALSE.
If the lower end of the recommended thresholds are actual high-quality matches, you may consider slightly raising the threshold to allow more matches.

### 2.2 The Synonym Guardrail (Strict Distance)
While TM and Glossary thresholds are automated, no recommendation is made for the **Strict Distance Threshold** (`RAG_STRICT_DISTANCE_THRESHOLD`), as it can severely degrade the quality.

#### The Borderline Case Review
If you find the system is missing obvious synonyms (e.g., "Add" vs "Create") or being too risky, follow this workflow:

1.  **Scan the report**: Review the `Synonym Guardrail Analysis` block in the summary report (in the terminal or the `rag_performance_report_*.md` file).
2.  **Inspect `rejected_matches_*.csv`**: sort (ascending) by distance and filter for `no_shared_words: TRUE` and `dist < 0.20`.
3.  **Adjust `.env`**:
    *   **If too strict**: Increase the threshold (e.g., `0.12` → `0.15`) to accept more synonyms.
    *   **If too loose**: Decrease the threshold to reject "False Friends" (e.g., "Send" vs "Submit").
4.  **Re-verify**: Recreate the proxy container, run a fresh translation, and re-run `analyse.sh`.

> [!IMPORTANT]
> **Re-running Analysis**: If you change any threshold in `.env`, you must recreate the proxy container (`docker compose up -d --force-recreate rag-proxy`) and generate fresh logs before re-running the analysis script.
>
> **Model-Specific Calibration**: These thresholds are calibrated to the **`BAAI/bge-large-en-v1.5`** embedding model. If you change models, these absolute distance numbers are no longer valid and must be recalculated.

---

## 3. Understanding Performance Metrics

The analysis report evaluates how effectively the RAG system assists the LLM.

### Metric Definitions
| Metric | Definition |
| :--- | :--- |
| **Total Attempts** | Unique source strings processed across all batches. |
| **Accepted Matches** | Matches passing both Distance Thresholds and Linguistic Guardrails. |
| **Precision** | Percentage of vector-similar matches that were linguistically relevant. |
| **Coverage** | Percentage of total strings that received RAG assistance. |
| **Distance Rejected** | Matches excluded because they exceeded the `TM` or `Glossary` thresholds. |
| **Guardrail Blocked** | Matches within distance but rejected for lacking lexical overlap. |

### Statistical Logic: The 95th Percentile
The system identifies the boundary where 95% of your previously "Accepted" matches sit. This boundary becomes the new recommendation, ensuring the system adapts to the empirical quality of your specific dataset while excluding extreme outliers.

**Note on "Residual Noise"**: Because this is a statistical approach, the recommended threshold may still include a small percentage of irrelevant matches (noise) or exclude some high-quality ones. This is why manual verification of the boundary cases in the exported CSVs is a required final step.

**Mean Distance Note**: Lower values indicate better "Average Match Closeness." A significant increase over time signals "Signal Drift" or a "crowded" database where false-friends become more common.

---

## 4. Maintenance & Data Growth

### When to Re-calibrate
*   **Initial Setup**: Establish your baseline.
*   **Significant Ingestion**: Every ~5,000 new strings, as the vector space becomes more crowded.
*   **Quality Drift**: If users observe incorrect context suggestions.
*   **Model Upgrades**: Mandatory re-calibration.

### The Core Principle
**False positives (incorrect context) are more detrimental than false negatives (no context).**
If the RAG data is missing, the LLM safely relies on its internal knowledge. If RAG provides incorrect context, it can corrupt the translation. **When in doubt, prioritize a stricter threshold.**
