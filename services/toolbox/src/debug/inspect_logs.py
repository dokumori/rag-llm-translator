'''
Diagnostic script to parse and inspect raw debug logs containing "FINAL_PAYLOAD:" lines.

What this script does:
1. Reads a specified log file (e.g., debug_run.log).
2. Searches for lines containing "FINAL_PAYLOAD:".
3. Parses the clean JSON payload.
4. Extracts and prints the System Prompt and User Messages.
5. Flags any messages containing RAG content.

How to run from host:
  docker compose exec toolbox python3 /app/src/debug/inspect_logs.py /path/to/logfile.log
'''
import sys
import json
import re


def inspect_log(filename):
    print(f"🔍 Reading {filename}...\n")

    found_any = False

    with open(filename, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            if "FINAL_PAYLOAD:" not in line:
                continue

            found_any = True

            try:
                # Logic: Get everything after "FINAL_PAYLOAD: "
                # The logger adds a space after the colon usually.
                parts = line.split("FINAL_PAYLOAD:", 1)
                if len(parts) < 2:
                    continue
                
                json_str = parts[1].strip()
                data = json.loads(json_str)
                
                model = data.get('model', 'unknown')
                messages = data.get('messages', [])

                # --- PRINT RESULTS ---
                print(f"✅ Found payload on line {line_num}. Model: {model}\n")

                for i, msg in enumerate(messages):
                    role = msg.get('role', 'unknown').upper()
                    content = msg.get('content', '')

                    print(f"--- [MESSAGE {i+1}: {role}] ---")
                    
                    if role == "SYSTEM":
                        # 1. Print first 200 characters (Intro/Instructions)
                        print(f"{content[:200]} ... [intermediate boilerplate hidden]\n")
                        
                        # 2. Extract and print RAG tags
                        glossary_match = re.search(r"<glossary_matches>.*?</glossary_matches>", content, re.DOTALL)
                        tm_match = re.search(r"<tm_matches>.*?</tm_matches>", content, re.DOTALL)

                        last_pos = 200
                        if glossary_match:
                            print("--- [GLOSSARY MATCHES] ---")
                            print(f"{glossary_match.group(0)}\n")
                            last_pos = max(last_pos, glossary_match.end())
                        
                        if tm_match:
                            print("--- [TM MATCHES] ---")
                            print(f"{tm_match.group(0)}\n")
                            last_pos = max(last_pos, tm_match.end())

                        # 3. Print the rest (usually the final task/text)
                        if last_pos < len(content):
                            print("--- [REMAINING PROMPT] ---")
                            print(f"{content[last_pos:].strip()}\n")
                    else:
                        # User message - Show full content as requested
                        print(f"{content}")
                    
                    print("")
                
                print("="*60 + "\n")

            except json.JSONDecodeError as e:
                print(f"❌ JSON Decode Error on line {line_num}: {e}")
            except Exception as e:
                print(f"❌ Error parsing line {line_num}: {e}")

    if not found_any:
        print("❌ No 'FINAL_PAYLOAD:' lines found. Check debug_run.log content.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 inspect_logs.py debug_run.log")
    else:
        inspect_log(sys.argv[1])
