import sys
import os
import subprocess
import glob
import shutil
import argparse
import logging
import tempfile
import time
from typing import List, Dict
from core.config import load_models_config

# --- Logging Configuration ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Constants
MAX_RETRIES = 2
BULK_SIZE = os.environ.get("BULK_SIZE", "15")


def get_env_config(skip_rag: bool = False) -> Dict[str, str]:
    """Returns the environment configuration for the translation tool."""
    env = os.environ.copy()
    env["OPENAI_API_KEY"] = "dummy"

    # Allow override via environment variable, default to http://rag-proxy:5000/v1
    base_url = os.environ.get("OPENAI_BASE_URL", "http://rag-proxy:5000/v1")
    
    if skip_rag:
        # Append /skip_rag to path directly instead of a query parameter which breaks /models resolution
        base_url = f"{base_url.rstrip('/')}/skip_rag"

    env["OPENAI_BASE_URL"] = base_url

    logger.info(f"🔧 Config: OPENAI_BASE_URL = {base_url}")

    return env


def find_po_files(input_dir: str) -> List[str]:
    """Finds all .po files in the input directory (top level only)."""
    return glob.glob(os.path.join(input_dir, "*.po"))


def prepare_command(model: str, target_lang: str, temp_folder: str) -> List[str]:
    """Prepares the gpt-po-translator command arguments."""
    return [
        sys.executable,
        "-m", "python_gpt_po.main",
        "--provider", "openai",
        "--model", model,
        "--folder", temp_folder,
        "--lang", target_lang,
        "--bulk",
        "--bulksize", BULK_SIZE
    ]


def execute_translation(cmd: List[str], env: Dict[str, str], max_retries: int = MAX_RETRIES) -> subprocess.CompletedProcess:
    """
    Executes the translation command with retries.
    Returns the result object if successful, or raises Exception after retries exhausted.
    """
    attempt = 0
    last_exception = None

    while attempt <= max_retries:
        try:
            # Clear previous attempt state
            last_exception = None
            last_result = None

            # capture_output = True allows capturing stdout/stderr for logging
            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True
            )
            
            last_result = result

            if result.returncode == 0:
                return result

            logger.warning(
                f"Attempt {attempt + 1} failed with exit code {result.returncode}.")
            logger.warning(f"STDERR: {result.stderr}")

        except Exception as e:
            # Clear previous attempt state
            last_result = None
            last_exception = e
            logger.error(f"Attempt {attempt + 1} raised exception: {e}")

        attempt += 1
        if attempt <= max_retries:
            wait_time = 2 ** attempt  # Exponential backoff: 2s, 4s
            logger.info(f"Retrying in {wait_time} seconds...")
            time.sleep(wait_time)

    # Return the last failed result if we have one, otherwise raise the system error
    if last_result is not None:
        return last_result
    elif last_exception:
        raise last_exception
    else:
        raise Exception(f"Command failed after {max_retries} retries.")


def run_translation_workflow(model: str, input_base_dir: str, output_base_dir: str, model_slug: str, rag_mode: str, timestamp: str, skip_rag: bool = False) -> None:
    """
    Main orchestration function for the translation workflow.
    """
    # 1. Setup
    target_lang = os.environ.get("TARGET_LANG", "ja")

    # Ensure output directory exists
    os.makedirs(output_base_dir, exist_ok=True)

    # 2. Find Files
    po_files = find_po_files(input_base_dir)

    if not po_files:
        logger.warning(
            "⚠️ No .po files found in {input_base_dir}. No requests will be sent.")
        return

    total_files = len(po_files)
    # Check if this model is marked as a dry run in the models config
    is_dry_run = False
    try:
        models_list = load_models_config()
        for m in models_list:
            if m["id"] == model:
                is_dry_run = bool(m.get("is_dry_run", False))
                break
    except Exception as e:
        logger.warning(f"Could not read models config to check dry_run flag: {e}")

    if is_dry_run:
        logger.info(f"🚀 Found {total_files} files. Starting translation in Dry Run Mode for '{target_lang}'...")
    else:
        logger.info(f"🚀 Found {total_files} files. Starting translation with model '{model}' for '{target_lang}'...")

    success_count = 0
    failure_count = 0

    env = get_env_config(skip_rag=skip_rag)

    logger.info(f"📁 Output will be written to: {output_base_dir}")

    # 3. Process Loop with Tempfile Context
    for index, src_file in enumerate(po_files, 1):
        filename = os.path.basename(src_file)
        
        # Construct new filename
        basename_no_ext, ext = os.path.splitext(filename)
        new_filename = f"{basename_no_ext}_{model_slug}_{rag_mode}_{timestamp}{ext}"
        
        final_dest_file = os.path.join(output_base_dir, new_filename)

        logger.info(
            f"[{index}/{total_files}] 📦 Processing: {filename}")

        try:
            # We use a TemporaryDirectory to cleanly isolate each file processing
            with tempfile.TemporaryDirectory() as temp_work_dir:

                temp_file_path = os.path.join(temp_work_dir, filename)
                shutil.copy2(src_file, temp_file_path)

                # B. PREPARE COMMAND
                cmd = prepare_command(model, target_lang, temp_work_dir)

                # C. EXECUTE
                result = execute_translation(cmd, env)

                # D. HANDLE RESULT
                if result.returncode == 0:
                    if not os.path.exists(temp_file_path):
                        logger.error(
                            f"   ❌ Error: Output file {filename} missing from {temp_work_dir} after successful run.")
                        failure_count += 1
                        continue
                    elif not os.path.isfile(temp_file_path):
                        logger.error(f"   ❌ Error: Output path is not a file: {temp_file_path}")
                        failure_count += 1
                        continue
                    elif os.path.getsize(temp_file_path) == 0:
                        logger.error(f"   ❌ Error: Output file is empty: {temp_file_path}")
                        failure_count += 1
                        continue
                    else:
                        try:
                            shutil.copy2(temp_file_path, final_dest_file)
                            logger.info(f"   ✅ Saved to: {final_dest_file}")
                            success_count += 1
                        except (PermissionError, OSError) as e:
                            logger.error(f"   ❌ Error copying file to destination {final_dest_file}: {e}")
                            failure_count += 1
                            continue
                else:
                    logger.error(
                        f"   ❌ Tool execution failed for {filename} (Exit Code: {result.returncode})")
                    failure_count += 1

        except Exception as e:
            logger.critical(
                f"   ❌ Critical Error on {filename}: {e}", exc_info=True)
            failure_count += 1

    # 4. Summary
    logger.info("=" * 30)
    logger.info("🎉 Translation run complete.")
    logger.info(
        f"📊 Summary: {success_count} Success, {failure_count} Failed, {total_files} Total")
    logger.info("=" * 30)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run translations on .po files")
    parser.add_argument("--model", required=True, help="LLM Model ID")
    parser.add_argument("--input", required=True, help="Input directory")
    parser.add_argument("--output", required=True, help="Output directory")
    parser.add_argument("--model-slug", required=True, help="Model slug for numbering")
    parser.add_argument("--rag-mode", required=True, help="RAG mode label")
    parser.add_argument("--timestamp", required=True, help="Run timestamp")
    parser.add_argument("--skip-rag", action="store_true", help="Bypass RAG semantic lookup entirely")

    args = parser.parse_args()

    run_translation_workflow(args.model, args.input, args.output, args.model_slug, args.rag_mode, args.timestamp, skip_rag=args.skip_rag)
