'''
Dumps the logs of the recent runs for the analysis of the threshold.
Because the logs accummulate over multiple runs, make sure you
purge the logs before starting a fresh run. This can be done by
using the interactive prompt at the end of `bash bin/analyse.sh`.
'''

import sys
import json
import csv
import statistics
from collections import defaultdict
import os
import logging
import datetime
import io
from typing import List, Dict, Any, Optional

# --- Logging Configuration ---
# Note: For this analysis script which outputs a report to stdout,
# we configure logging to stderr so it doesn't interfere with potential piping,
# although the user instruction said "Keep print() only if it is strictly necessary for final data output".
# We will use logger for status (loading/processing) and print for the final stats table.
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    level=logging.WARNING
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
    print(f"🔧 Config: RAG_ANALYSIS_DIR = {RAG_ANALYSIS_DIR}", file=sys.stderr)

    base_dir = RAG_ANALYSIS_DIR
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    matches_csv = os.path.join(base_dir, f"matches_{timestamp}.csv")
    misses_csv = os.path.join(base_dir, f"rejected_matches_{timestamp}.csv")
    report_md = os.path.join(base_dir, f"rag-performance-report_{timestamp}.md")

    if not os.path.exists(log_file):
        logger.error(f"❌ Log file not found: {log_file}")
        sys.exit(1)

    print(f"📊 Analysing {log_file}...", file=sys.stderr)

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

                # Ignore inspection logs to prevent double-counting
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

    print(f"✅ Processed {len(all_entries)} translation batches.", file=sys.stderr)
    print(f"✅ Found {len(rag_data)} potential RAG matches.", file=sys.stderr)
    print(f"🛡️ Guardrail Rejections: {guardrail_rejections}", file=sys.stderr)
    if skipped_lines > 0:
        print(
            f"⚠️ Skipped {skipped_lines} lines (non-JSON metadata irrelevant to analysis).", file=sys.stderr)

    if not rag_data:
        print("⚠️ No RAG matches found to analyse.", file=sys.stderr)
        sys.exit(0)

    # Deduplicate: the same query string can appear in multiple translation
    # batches, which would inflate statistics. Keep first occurrence only.
    seen_keys: set = set()
    unique_rag_data: List[Dict[str, Any]] = []
    for m in rag_data:
        key = (m['type'], m['untranslated_string'], m['rag_context'])
        if key not in seen_keys:
            seen_keys.add(key)
            unique_rag_data.append(m)
    duplicates_removed = len(rag_data) - len(unique_rag_data)
    if duplicates_removed > 0:
        print(
            f"🔁 Deduplicated: {duplicates_removed} duplicate RAG matches removed "
            f"({len(rag_data) + duplicates_removed} → {len(unique_rag_data)} unique).", file=sys.stderr)
    rag_data = unique_rag_data

    # Separate Matches and Misses
    accepted_matches = [m for m in rag_data if m.get('accepted', False)]
    rejected_matches = [m for m in rag_data if not m.get('accepted', False)]

    # --- Statistics Calculation ---
    stats = defaultdict(list)
    for item in rag_data:
        stats[item['type']].append(item['dist'])

    # --- REPORT OUTPUT ---
    report_buffer = io.StringIO()
    # We will print to this buffer as well as stdout for the report
    def report_print(msg: str = "") -> None:
        print(msg)
        report_buffer.write(msg + "\n")

    report_print("\n--- 📏 Distance Statistics ---")
    report_print(f"{'type':<10} {'count':<6} {'mean':<10} {'95%':<10} {'min':<10} {'25%':<10} {'50%':<10} {'75%':<10} {'max':<10}")

    for r_type, distances in stats.items():
        if not distances:
            continue
        count = len(distances)
        mean_val = statistics.mean(distances)
        p95 = statistics.quantiles(distances, n=20)[18] if count > 1 else distances[0]
        min_val = min(distances)
        max_val = max(distances)
        quantiles = statistics.quantiles(distances, n=4) if count > 1 else [
            min_val, min_val, min_val]

        report_print(
            f"{r_type:<10} {count:<6} {mean_val:<10.6f} {p95:<10.6f} {min_val:<10.6f} {quantiles[0]:<10.6f} {quantiles[1]:<10.6f} {quantiles[2]:<10.6f} {max_val:<10.6f}")

    report_print("\n--- 🎯 Acceptance Rate ---")
    report_print(f"Accepted: {len(accepted_matches)}")
    report_print(f"Rejected: {len(rejected_matches)}")

    # --- CSV Export Function ---
    def export_csv(data: List[Dict[str, Any]], filename: str) -> bool:
        if not data:
            return False
        # We need to ensure we grab the timestamp from the parent entry if not present,
        # but strictly speaking, the flattened rag_data might lack context if not carefully constructed.
        # However, for this simple analysis, we'll dump what we have in the rag_data dictionaries.

        # Pre-check keys exists in data to avoid errors, defaulting to empty string
        fieldnames = ["type", "untranslated_string", "rag_context", "tgt", "dist", "accepted", "no_shared_words"]

        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for row in data:
                writer.writerow({k: row.get(k, '') for k in fieldnames})
        return True

    print("💾 Exporting Data...", file=sys.stderr)

    # Export Misses
    if export_csv(rejected_matches, misses_csv):
        print(f"✅ Rejected matches saved to: {misses_csv}", file=sys.stderr)
    else:
        print("ℹ️ No rejected matches to save.", file=sys.stderr)

    # Export Matches
    if export_csv(accepted_matches, matches_csv):
        print(f"✅ Accepted matches saved to: {matches_csv}", file=sys.stderr)
    else:
        print("ℹ️ No accepted matches to save.", file=sys.stderr)

    # --- 💡 Recommended Configuration ---
    if not accepted_matches:
        logger.warning(
            "⚠️ No accepted matches found. Cannot calculate recommended settings.")
    else:
        report_print("\n--- 💡 Recommended Settings ---")
        report_print(f"Based on {len(accepted_matches)} accepted matches:")

        # 1. Calculate Thresholds (95th Percentile with Hard Cap)
        accepted_by_type = defaultdict(list)
        for m in accepted_matches:
            accepted_by_type[m['type']].append(m['dist'])

        for m_type in ['glossary', 'tm']:
            dists = accepted_by_type.get(m_type, [])
            if not dists:
                report_print(f"- {m_type}_threshold: N/A (no accepted matches)")
                continue

            max_dist = max(dists)
            
            # Rule: 95th Percentile
            # Constraint: Never exceed Max + 0.05 buffer
            if len(dists) > 1:
                # n=20 splits into 5% buckets. [18] gets the boundary between 90th-95th and 95th-100th, which is the 95th percentile.
                p95 = statistics.quantiles(dists, n=20)[18]
                hard_cap = max_dist + 0.05
                rec_threshold = min(p95, hard_cap)
            else:
                # Cannot calculate quantiles with less than 2 data points
                rec_threshold = max_dist + 0.05

            label = f"{m_type}_threshold:"
            report_print(f"- {label:<20} {rec_threshold:.2f}")
        report_print("- Explanation:")
        report_print("  • Thresholds: Calculated using the 95th percentile of valid matches, capped at max observed + 0.05.")
        report_print("  • Purpose:    Ensures most valid matches are included while capping the tolerance to prevent")
        report_print("                low-quality 'False Friends' from entering the translation context.")

        # Diagnostic: Average Match Closeness (read-only health metric)
        all_accepted_dists = [m['dist'] for m in accepted_matches]
        avg_dist = statistics.mean(all_accepted_dists)
        report_print(f"\n--- 🩺 Diagnostics ---")
        report_print(f"Average Match Closeness: {avg_dist:.4f} (range: 0.0–1.0, lower = tighter matches)")

    # --- 🔍 Synonym Guardrail Analysis ---
    # This section helps evaluate whether RAG_STRICT_DISTANCE_THRESHOLD is appropriate
    # for the current dataset. It requires the 'no_shared_words' field in log entries
    # (added to app.py). Older logs without this field are skipped gracefully.
    strict_threshold = float(os.environ.get("RAG_STRICT_DISTANCE_THRESHOLD", 0.08))
    no_word_matches = [m for m in rag_data if m.get('no_shared_words', False)]

    if no_word_matches:
        report_print(f"\n--- 🔍 Synonym Guardrail Analysis ---")
        report_print(f"Strict threshold in use: {strict_threshold:.2f} (RAG_STRICT_DISTANCE_THRESHOLD)")
        report_print(f"Total unique RAG matches: {len(rag_data)}")
        report_print(f"Matches that shared zero linguistic words/stems: {len(no_word_matches)}")

        # Define distance buckets dynamically around the configured strict threshold
        borderline_high = round(strict_threshold + 0.02, 4)
        buckets = [
            (0.00, strict_threshold, f"0.00–{strict_threshold:.2f} (within strict threshold)"),
            (strict_threshold, borderline_high, f"{strict_threshold:.2f}–{borderline_high:.2f} (borderline — review these)"),
        ]
        
        # Add remaining buckets starting from borderline_high, skipping bounds that are too low
        next_start = borderline_high
        for upper in [0.15, 0.20]:
            if next_start < upper:
                buckets.append((next_start, upper, f"{next_start:.2f}–{upper:.2f}"))
                next_start = upper
        buckets.append((next_start, float('inf'), f"{next_start:.2f}+"))

        report_print(f"\n  {'Distance Range':<42} {'Count':>6}  {'Status'}")
        for low, high, label in buckets:
            in_bucket = [m for m in no_word_matches if low <= m['dist'] < high]
            count = len(in_bucket)
            if count == 0:
                continue

            if high <= strict_threshold:
                status = "✅ ACCEPTED (below strict threshold)"
            elif low == strict_threshold:
                status = "⚠️  REJECTED — potential synonyms?"
            else:
                status = "❌ REJECTED"
            report_print(f"  {label:<42} {count:>6}  {status}")

            # Show up to 3 examples for the borderline bucket to aid manual review
            if low == strict_threshold and count > 0:
                for example in in_bucket[:3]:
                    report_print(f"     e.g. '{example['untranslated_string']}' vs '{example['rag_context']}' (dist: {example['dist']:.4f})")
        report_print("\n  ℹ️  To adjust RAG_STRICT_DISTANCE_THRESHOLD, see: docs/3_RAG_performance_analysis.md")
    # --- 📊 Performance Summary Table ---
    # This table matches the documentation in docs/3_RAG_performance_analysis.md
    glossary_threshold = float(os.environ.get("GLOSSARY_THRESHOLD", 0.35))
    tm_threshold = float(os.environ.get("TM_THRESHOLD", 0.32))

    # Total unique strings processed (from all_entries)
    unique_strings: set = set()
    for entry in all_entries:
        for item in entry.get('input_text', []):
            text = item.get('text', '') if isinstance(item, dict) else str(item)
            if text:
                unique_strings.add(text)
    total_strings = len(unique_strings)
    print(f"✅ Unique source strings: {total_strings}", file=sys.stderr)

    # Compute rows first so we can render to both terminal and markdown
    perf_rows = []
    for m_type in ['glossary', 'tm']:
        type_data = [m for m in rag_data if m['type'] == m_type]
        threshold = glossary_threshold if m_type == 'glossary' else tm_threshold

        accepted = len([m for m in type_data if m['accepted']])
        blocked = len([m for m in type_data if not m['accepted'] and m['dist'] < threshold])
        rejected = len([m for m in type_data if m['dist'] >= threshold])

        precision = (accepted / (accepted + blocked) * 100) if (accepted + blocked) > 0 else 0
        coverage = (accepted / total_strings * 100) if total_strings > 0 else 0
        perf_rows.append((m_type, total_strings, accepted, blocked, rejected, precision, coverage))

    # Print plain-text table to terminal (no markdown pipes)
    print("\n--- 📊 Performance Summary ---")
    print(f"{'Type':<10} {'Total':<8} {'Accepted':<10} {'Guardrail Blocked':<19} {'Dist. Rejected':<16} {'Precision':>10} {'Coverage':>10}")
    for m_type, total_strings, accepted, blocked, rejected, precision, coverage in perf_rows:
        print(f"{m_type.upper():<10} {total_strings:<8} {accepted:<10} {blocked:<19} {rejected:<16} {precision:>9.1f}% {coverage:>9.1f}%")

    # --- Save Markdown Report ---
    try:
        report_content = report_buffer.getvalue()

        with open(report_md, 'w', encoding='utf-8') as f:
            f.write(f"# RAG Performance Report\n")
            f.write(f"Generated: {timestamp}\n\n")

            f.write("## Distance Statistics\n\n")
            f.write("| Type | Count | Mean | 95% | Min | 25% | 50% | 75% | Max |\n")
            f.write("|---|---|---|---|---|---|---|---|---|\n")
            for r_type, distances in stats.items():
                if not distances:
                    continue
                count = len(distances)
                mean_val = statistics.mean(distances)
                p95 = statistics.quantiles(distances, n=20)[18] if count > 1 else distances[0]
                min_val = min(distances)
                max_val = max(distances)
                quantiles = statistics.quantiles(distances, n=4) if count > 1 else [min_val, min_val, min_val]
                f.write(f"| {r_type} | {count} | {mean_val:.6f} | {p95:.6f} | {min_val:.6f} | {quantiles[0]:.6f} | {quantiles[1]:.6f} | {quantiles[2]:.6f} | {max_val:.6f} |\n")

            f.write("\n## Acceptance Rate\n\n")
            f.write(f"- **Accepted:** {len(accepted_matches)}\n")
            f.write(f"- **Rejected:** {len(rejected_matches)}\n")

            if accepted_matches:
                accepted_by_type_md = defaultdict(list)
                for m in accepted_matches:
                    accepted_by_type_md[m['type']].append(m['dist'])

                f.write("\n## Recommended Settings\n\n")
                for m_type in ['glossary', 'tm']:
                    dists = accepted_by_type_md.get(m_type, [])
                    if not dists:
                        f.write(f"- `{m_type}_threshold`: N/A (no accepted matches)\n")
                        continue
                    max_dist = max(dists)
                    if len(dists) > 1:
                        p95 = statistics.quantiles(dists, n=20)[18]
                        rec_threshold = min(p95, max_dist + 0.05)
                    else:
                        rec_threshold = max_dist + 0.05
                    f.write(f"- `{m_type}_threshold`: **{rec_threshold:.2f}**\n")

                f.write("\n**Explanation:** Thresholds calculated using the 95th percentile of valid matches, capped at max observed + 0.05. Prevents low-quality ‘False Friends’ from entering the translation context.\n")

                all_accepted_dists = [m['dist'] for m in accepted_matches]
                avg_dist = statistics.mean(all_accepted_dists)
                f.write("\n## Diagnostics\n\n")
                f.write(f"- **Average Match Closeness:** {avg_dist:.4f} *(range: 0.0–1.0, lower = tighter matches)*\n")

            if no_word_matches:
                f.write("\n## Synonym Guardrail Analysis\n\n")
                f.write(f"- **Strict threshold in use:** {strict_threshold:.2f} (`RAG_STRICT_DISTANCE_THRESHOLD`)\n")
                f.write(f"- **Total unique RAG matches:** {len(rag_data)}\n")
                f.write(f"- **Matches that shared zero linguistic words/stems:** {len(no_word_matches)}\n\n")
                f.write("| Distance Range | Count | Status |\n")
                f.write("|---|---|---|\n")
                borderline_high_md = round(strict_threshold + 0.02, 4)
                buckets_md = [
                    (0.00, strict_threshold, f"0.00–{strict_threshold:.2f} (within strict threshold)"),
                    (strict_threshold, borderline_high_md, f"{strict_threshold:.2f}–{borderline_high_md:.2f} (borderline — review these)"),
                ]
                next_start = borderline_high_md
                for upper in [0.15, 0.20]:
                    if next_start < upper:
                        buckets_md.append((next_start, upper, f"{next_start:.2f}–{upper:.2f}"))
                        next_start = upper
                buckets_md.append((next_start, float('inf'), f"{next_start:.2f}+"))
                for low, high, label in buckets_md:
                    in_bucket = [m for m in no_word_matches if low <= m['dist'] < high]
                    count_b = len(in_bucket)
                    if count_b == 0:
                        continue
                    if high <= strict_threshold:
                        status_md = "✅ ACCEPTED"
                    elif low == strict_threshold:
                        status_md = "⚠️ REJECTED — potential synonyms?"
                    else:
                        status_md = "❌ REJECTED"
                    f.write(f"| {label} | {count_b} | {status_md} |\n")
                    if low == strict_threshold and count_b > 0:
                        f.write("\n**Borderline Examples:**\n")
                        for example in in_bucket[:3]:
                            f.write(f"- `{example['untranslated_string']}` vs `{example['rag_context']}` (dist: {example['dist']:.4f})\n")
                        f.write("\n")
                f.write("\n> To adjust `RAG_STRICT_DISTANCE_THRESHOLD`, see `docs/3_RAG_performance_analysis.md`.\n")

            f.write("\n## Performance Summary\n\n")
            f.write("| Type | Total Attempts | Accepted Matches | Guardrail Blocked | Distance Rejected | Precision (Linguistic) | Coverage (RAG) |\n")
            f.write("|---|---|---|---|---|---|---|\n")
            for m_type, total_strings, accepted, blocked, rejected, precision, coverage in perf_rows:
                f.write(f"| **{m_type.upper()}** | {total_strings} | {accepted} | {blocked} | {rejected} | {precision:.1f}% | {coverage:.1f}% |\n")

        print(f"REPORT_FILE={report_md}")
    except Exception as e:
        logger.error(f"❌ Failed to save report: {e}")



if __name__ == "__main__":
    main()
