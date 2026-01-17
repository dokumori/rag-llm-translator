import re
import ast
import sys


def inspect_log(filename):
    print(f"🔍 Reading {filename}...\n")

    found_any = False

    with open(filename, 'r') as f:
        for line_num, line in enumerate(f, 1):
            if "Request options:" not in line:
                continue

            found_any = True

            # METHOD CHANGE: Split string instead of Regex
            # This captures everything from "Request options:" to the end of the line
            try:
                # Get the part after "Request options: "
                raw_dict_str = line.split("Request options:", 1)[1].strip()

                # FIX 1: Sanitize "Timeout(...)" object which crashes ast.literal_eval
                # We replace Timeout(connect=...) with None or a string
                clean_dict_str = re.sub(
                    r"Timeout\([^)]+\)", "'Timeout_Ignored'", raw_dict_str)

                # FIX 2: Parse safely
                data = ast.literal_eval(clean_dict_str)
                json_payload = data.get('json_data', {})

                # --- PRINT RESULTS ---
                print(
                    f"✅ Found request on line {line_num}. Content summary:\n")

                # 1. Check System Prompt
                system_prompt = json_payload.get('system', "NOT FOUND")
                print(f"--- [SYSTEM PROMPT] ---\n{system_prompt}\n")

                # 2. Check User Messages
                messages = json_payload.get('messages', [])
                for i, msg in enumerate(messages):
                    role = msg.get('role', 'unknown').upper()
                    content = msg.get('content', '')

                    print(f"--- [MESSAGE {i+1}: {role}] ---")
                    # Print first 1000 chars
                    print(
                        content[:1000] + ("\n... [truncated]" if len(content) > 1000 else ""))

                    # Check for RAG indicators
                    if "Example" in content or "Reference" in content:
                        print(
                            "\n👀 NOTICE: 'Example' or 'Reference' detected. RAG context likely present.")
                    else:
                        print(
                            "\n⚠️ NOTICE: No obvious RAG keywords found in this message.")

                print("\n" + "="*50 + "\n")

                # Only show the first match to avoid flooding your screen?
                # Uncomment the next line if you only want to see the first one.
                # break

            except Exception as e:
                print(f"❌ Error parsing line {line_num}: {e}")
                # Debug helper: print the end of the string to see if it was cut off
                print(f"   End of string was: ...{clean_dict_str[-50:]}")

    if not found_any:
        print("❌ No 'Request options:' lines found. Check debug_run.log content.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 inspect_logs.py debug_run.log")
    else:
        inspect_log(sys.argv[1])
