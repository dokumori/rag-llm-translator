import os
import sys
import subprocess
import glob
import shutil
from tqdm import tqdm

def run_translation(model, input_base_dir, output_base_dir):
    # Temp directory to "trick" the tool into processing one file at a time
    TEMP_WORK_DIR = "/app/temp_work_dir"
    
    # Clean/Create output and temp dirs
    os.makedirs(output_base_dir, exist_ok=True)
    if os.path.exists(TEMP_WORK_DIR):
        shutil.rmtree(TEMP_WORK_DIR)
    os.makedirs(TEMP_WORK_DIR)

    # Find all .po files in the input folder
    po_files = glob.glob(os.path.join(input_base_dir, "**/*.po"), recursive=True)
    
    if not po_files:
        print(f"⚠️ No .po files found in {input_base_dir}")
        return

    print(f"🚀 Starting translation of {len(po_files)} files using {model}...")

    # Initialize Progress Bar
    with tqdm(total=len(po_files), unit="file", desc="Translating") as pbar:
        for src_file in po_files:
            # 1. Determine relative path (e.g., 'subfolder/en-ja.po')
            rel_path = os.path.relpath(src_file, input_base_dir)
            filename = os.path.basename(src_file)
            
            # 2. Determine final destination
            final_dest_file = os.path.join(output_base_dir, rel_path)
            final_dest_dir = os.path.dirname(final_dest_file)
            os.makedirs(final_dest_dir, exist_ok=True)

            # 3. Update Progress Bar
            pbar.set_description(f"Processing {filename[:20]}")

            # 4. ISOLATION STEP: Copy single file to temp dir
            # Clear temp dir first
            for f in glob.glob(os.path.join(TEMP_WORK_DIR, "*")):
                os.remove(f)
            
            temp_file_path = os.path.join(TEMP_WORK_DIR, filename)
            shutil.copy(src_file, temp_file_path)

            try:
                # 5. Run Tool on the TEMP folder
                cmd = [
                    "gpt-po-translator",
                    "--provider", "anthropic",
                    "--model", model,
                    "--folder", TEMP_WORK_DIR, # Tool processes this folder
                    "--lang", "ja",
                    "--bulk",
                    "--bulksize", "15"
                    # Note: API Keys and Base URL are passed via env vars automatically
                ]
                
                result = subprocess.run(
                    cmd, 
                    capture_output=True, 
                    text=True, 
                    env=os.environ.copy()
                )

                if result.returncode != 0:
                    tqdm.write(f"\n❌ Error processing {rel_path}:")
                    tqdm.write(result.stderr)
                else:
                    # 6. Success: Move processed file to final destination
                    # The tool usually updates the file in-place or creates a new one in the folder
                    # We assume in-place update for the file in TEMP_WORK_DIR
                    if os.path.exists(temp_file_path):
                        shutil.copy(temp_file_path, final_dest_file)
                    else:
                        tqdm.write(f"\n⚠️ Output file missing for {rel_path}")

            except Exception as e:
                tqdm.write(f"\n❌ Unexpected error on {rel_path}: {e}")
            
            pbar.update(1)

    # Cleanup
    if os.path.exists(TEMP_WORK_DIR):
        shutil.rmtree(TEMP_WORK_DIR)

if __name__ == "__main__":
    # We removed api_url arg since it's handled by env vars
    if len(sys.argv) < 3:
        print("Usage: python translate_runner.py <model> <input_dir> <output_dir>")
        sys.exit(1)

    model = sys.argv[1]
    input_dir = sys.argv[2]
    output_dir = sys.argv[3]

    run_translation(model, input_dir, output_dir)
