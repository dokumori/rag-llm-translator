'''
Dumps the logs of the recent runs for the analysis of the threshold.
Because the logs accummulate over multiple runs, make sure you
restart rag-proxy and flush the logs to delete unwanted logs from
the previous runs.
'''

import sys
import json
import csv
import statistics
from collections import defaultdict
import os
import logging
from typing import List, Dict, Any, Optional

# --- Logging Configuration ---
# Note: For this analysis script which outputs a report to stdout,
# we configure logging to stderr so it doesn't interfere with potential piping,
# although the user instruction said "Keep print() only if it is strictly necessary for final data output".
# We will use logger for status (loading/processing) and print for the final stats table.
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python3 analyse_logs.py <log_file>")
        sys.exit(1)

    log_file = sys.argv[1]

    # Output paths
    RAG_ANALYSIS_DIR = os.environ.get(
        "RAG_ANALYSIS_DIR", "/app/data/rag-analysis")
    logger.info(f"🔧 Config: RAG_ANALYSIS_DIR = {RAG_ANALYSIS_DIR}")

    base_dir = RAG_ANALYSIS_DIR
    matches_csv = os.path.join(base_dir, "matches.csv")
    misses_csv = os.path.join(base_dir, "near_misses.csv")

    if not os.path.exists(log_file):
        logger.error(f"❌ Log file not found: {log_file}")
        sys.exit(1)

    logger.info(f"📊 Analysing {log_file}...")

    all_entries = []
    rag_data = []

    # Read Log File
    skipped_lines = 0
    guardrail_rejections = 0
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            for line in f:
                # Check specifically for guardrail rejections (which are plain text logs)
                if "Guardrail Rejection" in line:
                    guardrail_rejections += 1
                    continue

                # [NEW] Ignore inspection logs to prevent double-counting
                if "FINAL_PAYLOAD" in line:
                    continue

                # Locate the start of the JSON payload
                json_start = line.find('{')
                if json_start == -1:
                    skipped_lines += 1
                    continue

                try:
                    json_str = line[json_start:]
                    entry = json.loads(json_str)

                    # Only process if it looks like our structured log
                    all_entries.append(entry)
                    if 'rag_matches' in entry and entry['rag_matches']:
                        rag_data.extend(entry['rag_matches'])

                except json.JSONDecodeError:
                    skipped_lines += 1
                    continue
    except Exception as e:
        logger.error(f"❌ Error reading log file: {e}", exc_info=True)
        sys.exit(1)

    logger.info(f"✅ Processed {len(all_entries)} translation requests.")
    logger.info(f"✅ Found {len(rag_data)} potential RAG matches.")
    logger.info(f"🛡️ Guardrail Rejections: {guardrail_rejections}")
    if skipped_lines > 0:
        logger.info(
            f"⚠️ Skipped {skipped_lines} lines (non-JSON metadata irrelevant to analysis).")

    if not rag_data:
        logger.warning("⚠️ No RAG matches found to analyse.")
        sys.exit(0)

    # Separate Matches and Misses
    accepted_matches = [m for m in rag_data if m.get('accepted', False)]
    rejected_matches = [m for m in rag_data if not m.get('accepted', False)]

    # --- Statistics Calculation ---
    stats = defaultdict(list)
    for item in rag_data:
        stats[item['type']].append(item['dist'])

    # --- REPORT OUTPUT (Keep as print for readability/piping) ---
    print("\n--- 📏 Distance Statistics ---")
    print(f"{'type':<10} {'count':<6} {'mean':<10} {'std':<10} {'min':<10} {'25%':<10} {'50%':<10} {'75%':<10} {'max':<10}")

    for r_type, distances in stats.items():
        if not distances:
            continue
        count = len(distances)
        mean_val = statistics.mean(distances)
        std_val = statistics.stdev(distances) if count > 1 else 0.0
        min_val = min(distances)
        max_val = max(distances)
        quantiles = statistics.quantiles(distances, n=4) if count > 1 else [
            min_val, min_val, min_val]

        print(
            f"{r_type:<10} {count:<6} {mean_val:<10.6f} {std_val:<10.6f} {min_val:<10.6f} {quantiles[0]:<10.6f} {quantiles[1]:<10.6f} {quantiles[2]:<10.6f} {max_val:<10.6f}")

    print("\n--- 🎯 Acceptance Rate ---")
    print(f"Accepted: {len(accepted_matches)}")
    print(f"Rejected: {len(rejected_matches)}")

    # --- CSV Export Function ---
    def export_csv(data: List[Dict[str, Any]], filename: str) -> bool:
        if not data:
            return False
        keys = ["timestamp", "type", "query", "src", "tgt", "dist", "accepted"]
        # We need to ensure we grab the timestamp from the parent entry if not present,
        # but strictly speaking, the flattened rag_data might lack context if not carefully constructed.
        # However, for this simple analysis, we'll dump what we have in the rag_data dictionaries.

        # Pre-check keys exists in data to avoid errors, defaulting to empty string
        fieldnames = ["type", "query", "src", "tgt", "dist", "accepted"]

        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for row in data:
                writer.writerow({k: row.get(k, '') for k in fieldnames})
        return True

    logger.info("💾 Exporting Data...")

    # Export Misses
    if export_csv(rejected_matches, misses_csv):
        logger.info(f"✅ Near misses saved to: {misses_csv}")
    else:
        logger.info(f"ℹ️ No near misses to save.")

    # Export Matches
    if export_csv(accepted_matches, matches_csv):
        logger.info(f"✅ Accepted matches saved to: {matches_csv}")
    else:
        logger.info(f"ℹ️ No accepted matches to save.")

    # --- 💡 Recommended Configuration ---
    if not accepted_matches:
        logger.warning(
            "⚠️ No accepted matches found. Cannot calculate recommended settings.")
    else:
        print("\n--- 💡 Recommended Settings ---")
        print(f"Based on {len(accepted_matches)} accepted matches:")

        # 1. Calculate Thresholds (3-Sigma Rule)
        accepted_by_type = defaultdict(list)
        for m in accepted_matches:
            accepted_by_type[m['type']].append(m['dist'])

        for m_type in ['glossary', 'tm']:
            dists = accepted_by_type.get(m_type, [])
            if not dists:
                print(f"- {m_type}_threshold: N/A (no accepted matches)")
                continue

            mean_val = statistics.mean(dists)
            std_val = statistics.stdev(dists) if len(dists) > 1 else 0.0

            # Rule: Mean + 3*StdDev (Cover 99.7% of valid matches)
            # Constraint: If std is 0 (single item), use Max + 0.05
            if std_val == 0:
                rec_threshold = max(dists) + 0.05
            else:
                rec_threshold = mean_val + (3 * std_val)

            print(f"- {m_type}_threshold: {rec_threshold:.2f}")

        # 2. Calculate Distance Sensitivity
        # Formula: 1.0 - (Mean of all accepted distances)
        # Constraint: Clamp between 0.5 and 0.9
        all_accepted_dists = [m['dist'] for m in accepted_matches]
        avg_dist = statistics.mean(all_accepted_dists)
        rec_sensitivity = 1.0 - avg_dist
        rec_sensitivity = max(0.5, min(0.9, rec_sensitivity))

        print(f"- distance_sensitivity: {rec_sensitivity:.2f}")

        print("- Explanation:")
        print("  • Thresholds: Calculated using Mean + 3σ to cover 99.7% of valid matches.")
        print("  • Sensitivity: Derived from average closeness (1.0 - avg_distance), clamped 0.5-0.9.")


if __name__ == "__main__":
    main()
