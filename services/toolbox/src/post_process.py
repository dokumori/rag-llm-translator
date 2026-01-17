import re
import sys
import os
import glob

def add_spaces_to_variables(text):
  def process_msgstr(match):
    msgstr_content = match.group(1)
    
    # Define Drupal variable pattern: starts with %, !, or @ followed by ASCII alphanumerics
    # We use [a-zA-Z0-9_] instead of \w to avoid matching Japanese characters
    
    # 1. Multibyte char followed by Variable
    # Example: "こんにちは%user" -> "こんにちは %user"
    msgstr_content = re.sub(r'([^\x00-\x7F])([%!@][a-zA-Z0-9_]+)', r'\1 \2', msgstr_content)
    
    # 2. Variable followed by Multibyte char
    # Example: "%userさん" -> "%user さん"
    msgstr_content = re.sub(r'([%!@][a-zA-Z0-9_]+)([^\x00-\x7F])', r'\1 \2', msgstr_content)
    
    return f'msgstr "{msgstr_content}"'

  return re.sub(r'msgstr "([^"]*)"', process_msgstr, text)

def process_single_file(file_path):
  try:
    print(f"🔧 Processing: {os.path.basename(file_path)}...")
    with open(file_path, 'r', encoding='utf-8') as f:
      content = f.read()

    new_content = add_spaces_to_variables(content)

    with open(file_path, 'w', encoding='utf-8') as f:
      f.write(new_content)
    print(f"✅ Fixed variables in: {file_path}")
  except Exception as e:
    print(f"❌ Failed to process {file_path}: {e}")

if __name__ == "__main__":
  # --- Configuration ---
  POST_PROCESS_INPUT_DIR = os.environ.get("POST_PROCESS_INPUT_DIR", "/app/po/output")
  
  if len(sys.argv) < 2:
    print(f"⚠️ No path provided. Defaulting to: {POST_PROCESS_INPUT_DIR}")
    input_path = POST_PROCESS_INPUT_DIR
  else:
    input_path = sys.argv[1]

  files_to_process = []

  # Logic: Handle both specific files and directories
  if os.path.isfile(input_path):
    files_to_process.append(input_path)
  elif os.path.isdir(input_path):
    # Find all .po files in the folder
    search_pattern = os.path.join(input_path, "*.po")
    files_to_process = glob.glob(search_pattern)
  else:
    print(f"❌ Error: Path not found: {input_path}")
    sys.exit(1)

  if not files_to_process:
    print(f"⚠️ No .po files found in {input_path}")
    sys.exit(0)

  for po_file in files_to_process:
    process_single_file(po_file)
