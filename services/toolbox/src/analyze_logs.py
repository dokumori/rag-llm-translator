'''
Dumps the logs of the recent runs for the analysis of the threshold.
Because the logs accummulate over multiple runs, make sure you
restart rag-proxy and flush the logs to delete unwanted logs from
the previous runs.
'''

import pandas as pd
import json
import sys
import os

# Display settings to prevent wrapping in console output
pd.set_option('display.max_colwidth', 60)
pd.set_option('display.width', 1000)

def clean_text(text):
    """Truncates text and removes newlines for table/CSV display."""
    if not isinstance(text, str):
        return str(text)
    # Collapse whitespace/newlines into single space
    text = " ".join(text.split())
    # Truncate if strictly necessary for console, but we want full text in CSV ideally.
    # We will keep the 50 char limit for console print, but apply it to CSV for tidiness 
    # unless you prefer full length. Let's keep it tidy.
    if len(text) > 50:
        return text[:47] + "..."
    return text

def analyze(log_file):
    print(f"📊 Analyzing {log_file}...\n")
    
    data = []
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    # Robust Fix: Find where JSON starts (ignoring Docker prefixes)
                    json_start = line.find('{')
                    if json_start != -1:
                        json_str = line[json_start:].strip()
                        entry = json.loads(json_str)
                        if "rag_matches" in entry:
                            data.append(entry)
                except:
                    continue
    except FileNotFoundError:
        print(f"❌ File not found: {log_file}")
        return

    if not data:
        print("❌ No valid log entries found.")
        return

    matches = []
    for entry in data:
        for m in entry.get("rag_matches", []):
            matches.append(m)
    
    df = pd.DataFrame(matches)
    
    print(f"✅ Processed {len(data)} translation requests.")
    print(f"✅ Found {len(df)} potential RAG matches.\n")

    if df.empty:
        return

    # Normalize column names (handle 'dist' vs 'distance')
    if "distance" in df.columns and "dist" not in df.columns:
        df["dist"] = df["distance"]
    
    # --- 1. PRINT STATISTICS TO CONSOLE ---
    print("--- 📏 Distance Statistics ---")
    if "dist" in df.columns:
        print(df.groupby("type")["dist"].describe())

    print("\n--- 🎯 Acceptance Rate ---")
    try:
        if "accepted" in df.columns:
            acceptance = df.groupby(["type", "accepted"]).size().unstack(fill_value=0)
            print(acceptance)
    except:
        print(df["accepted"].value_counts())

    # --- 2. CSV EXPORT LOGIC ---
    print("\n--- 💾 Exporting Data ---")
    
    # We capture a wider range (0.0 to 0.25) so you can compare 
    # "Good Matches" (0.0-0.13) vs "Near Misses/Bad Matches" (0.13-0.25)
    near_misses = df[(df["dist"] >= 0.0) & (df["dist"] < 0.25)].copy()

    if not near_misses.empty:
        # Sort by distance for easier reading
        near_misses = near_misses.sort_values("dist")
        
        # Apply cleaning to relevant text columns
        text_cols = ["query", "src", "tgt"]
        for col in text_cols:
            if col in near_misses.columns:
                near_misses[col] = near_misses[col].apply(clean_text)
        
        # Reorder columns: Query -> RAG Source -> Target -> Distance -> Accepted
        # This makes it easy to compare "What user asked" vs "What DB found"
        desired_cols = ["type", "dist", "accepted", "query", "src", "tgt"]
        existing_cols = [c for c in desired_cols if c in near_misses.columns]
        
        # Define output directory and path
        output_dir = "/app/data/rag-analysis"
        output_path = os.path.join(output_dir, "near_misses.csv")
        
        # Ensure directory exists
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        try:
            near_misses[existing_cols].to_csv(output_path, index=False)
            print(f"✅ Analysis saved to: {output_path}")
            print(f"   (Host location: data/rag-analysis/near_misses.csv)")
        except Exception as e:
            print(f"❌ Failed to save CSV: {e}")
            print("\nTop 5 Entries:")
            print(near_misses[existing_cols].head(5).to_string(index=False))
    else:
        print("No matches in the 0.0 - 0.25 range found to export.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 analyze_logs.py <logfile>")
        sys.exit(1)
    analyze(sys.argv[1])
