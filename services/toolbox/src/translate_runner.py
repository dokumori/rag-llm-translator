import os
import subprocess
import glob
import shutil
import argparse

# Drupal Standard: 2-space indent
def run_translation(model, input_base_dir, output_base_dir):
  # 1. Setup Directories
  # We use a temp dir to isolate files, ensuring the tool processes exactly one file at a time
  TEMP_WORK_DIR = "/tmp/temp_work_dir"
  if os.path.exists(TEMP_WORK_DIR):
    shutil.rmtree(TEMP_WORK_DIR)
  os.makedirs(TEMP_WORK_DIR)
  
  # Ensure output directory exists
  os.makedirs(output_base_dir, exist_ok=True)

  # Retrieve Target Language from environment, default to 'ja' if missing
  target_lang = os.environ.get("TARGET_LANG", "ja")

  # 2. Find files recursively
  po_files = glob.glob(os.path.join(input_base_dir, "**/*.po"), recursive=True)
  
  if not po_files:
    print(f"⚠️ No .po files found in {input_base_dir}", flush=True)
    return

  total_files = len(po_files)
  print(f"🚀 Found {total_files} files. Using gpt-po-translator with {model} for language '{target_lang}'...", flush=True)

  # 3. Process Loop
  for index, src_file in enumerate(po_files, 1):
    try:
      # Calculate paths
      rel_path = os.path.relpath(src_file, input_base_dir)
      filename = os.path.basename(src_file)
      final_dest_file = os.path.join(output_base_dir, rel_path)
      
      # Ensure final destination directory exists
      os.makedirs(os.path.dirname(final_dest_file), exist_ok=True)

      # Progress Log
      print(f"[{index}/{total_files}] 📦 Processing: {rel_path}", flush=True)

      # A. ISOLATION STEP: Clear temp and copy target file there
      # This mimics your original logic to force the tool to see only this file
      for f in glob.glob(os.path.join(TEMP_WORK_DIR, "*")):
        os.remove(f)
      
      temp_file_path = os.path.join(TEMP_WORK_DIR, filename)
      shutil.copy2(src_file, temp_file_path)

      # B. PREPARE COMMAND
      # We use '--folder' to match your original successful workflow
      cmd = [
        "gpt-po-translator",
        "--provider", "openai",
        "--model", model,
        "--folder", TEMP_WORK_DIR, 
        "--lang", target_lang, 
        "--bulk",
        "--bulksize", "15"
      ]

      # C. CONFIGURE ENVIRONMENT (Amazee/Proxy Connection)
      env = os.environ.copy()
      env["OPENAI_API_KEY"] = "dummy" 
      env["OPENAI_BASE_URL"] = "http://rag-proxy:5000/v1"

      # D. EXECUTE TOOL
      # capture_output=False lets the tool's own progress bar show in Docker logs
      result = subprocess.run(
        cmd,
        env=env,
        capture_output=False, 
        text=True
      )

      # E. HANDLE RESULT
      if result.returncode == 0:
        # Success: Move the processed file from temp to final destination
        if os.path.exists(temp_file_path):
          shutil.copy2(temp_file_path, final_dest_file)
          print(f"   ✅ Saved to: {final_dest_file}", flush=True)
        else:
          print(f"   ⚠️ Error: Output file missing in temp dir: {filename}", flush=True)
      else:
        print(f"   ❌ Tool execution failed for {rel_path} (Exit Code: {result.returncode})", flush=True)

    except Exception as e:
      print(f"   ❌ Critical Error on {rel_path}: {e}", flush=True)

  # Cleanup
  if os.path.exists(TEMP_WORK_DIR):
    shutil.rmtree(TEMP_WORK_DIR)
  
  print("🎉 Translation run complete.", flush=True)

if __name__ == "__main__":
  parser = argparse.ArgumentParser(description="Run translations on .po files")
  parser.add_argument("--model", required=True, help="LLM Model ID")
  parser.add_argument("--input", required=True, help="Input directory")
  parser.add_argument("--output", required=True, help="Output directory")

  args = parser.parse_args()

  run_translation(args.model, args.input, args.output)
