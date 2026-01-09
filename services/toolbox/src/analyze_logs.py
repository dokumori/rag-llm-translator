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

def main():
  if len(sys.argv) < 2:
    print("Usage: python3 analyze_logs.py <log_file>")
    sys.exit(1)

  log_file = sys.argv[1]
  
  # Output paths
  base_dir = "/app/data/rag-analysis"
  matches_csv = os.path.join(base_dir, "matches.csv")
  misses_csv = os.path.join(base_dir, "near_misses.csv")

  if not os.path.exists(log_file):
    print(f"❌ Log file not found: {log_file}")
    sys.exit(1)

  print(f"📊 Analyzing {log_file}...")

  all_entries = []
  rag_data = []

  # Read Log File
  try:
    with open(log_file, 'r', encoding='utf-8') as f:
      for line in f:
        try:
          entry = json.loads(line)
          all_entries.append(entry)
          if 'rag_matches' in entry and entry['rag_matches']:
            rag_data.extend(entry['rag_matches'])
        except json.JSONDecodeError:
          continue
  except Exception as e:
    print(f"❌ Error reading log file: {e}")
    sys.exit(1)

  print(f"\n✅ Processed {len(all_entries)} translation requests.")
  print(f"✅ Found {len(rag_data)} potential RAG matches.")

  if not rag_data:
    print("⚠️ No RAG matches found to analyze.")
    sys.exit(0)

  # Separate Matches and Misses
  accepted_matches = [m for m in rag_data if m.get('accepted', False)]
  rejected_matches = [m for m in rag_data if not m.get('accepted', False)]

  # --- Statistics Calculation ---
  stats = defaultdict(list)
  for item in rag_data:
    stats[item['type']].append(item['dist'])

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
    quantiles = statistics.quantiles(distances, n=4) if count > 1 else [min_val, min_val, min_val]
    
    print(f"{r_type:<10} {count:<6} {mean_val:<10.6f} {std_val:<10.6f} {min_val:<10.6f} {quantiles[0]:<10.6f} {quantiles[1]:<10.6f} {quantiles[2]:<10.6f} {max_val:<10.6f}")

  print("\n--- 🎯 Acceptance Rate ---")
  print(f"Accepted: {len(accepted_matches)}")
  print(f"Rejected: {len(rejected_matches)}")

  # --- CSV Export Function ---
  def export_csv(data, filename):
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

  print("\n--- 💾 Exporting Data ---")
  
  # Export Misses
  if export_csv(rejected_matches, misses_csv):
    print(f"✅ Near misses saved to: {misses_csv}")
  else:
    print(f"ℹ️ No near misses to save.")

  # Export Matches
  if export_csv(accepted_matches, matches_csv):
    print(f"✅ Accepted matches saved to: {matches_csv}")
  else:
    print(f"ℹ️ No accepted matches to save.")

if __name__ == "__main__":
  main()
