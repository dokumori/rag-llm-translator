import sys
import os
import subprocess
import glob
import shutil
import argparse
import logging
import tempfile
import time
from typing import List, Dict, Any, Optional

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


def get_env_config() -> Dict[str, str]:
    """Returns the environment configuration for the translation tool."""
    env = os.environ.copy()
    env["OPENAI_API_KEY"] = "dummy"

    # Allow override via environment variable, default to http://rag-proxy:5000/v1
    base_url = os.environ.get("OPENAI_BASE_URL", "http://rag-proxy:5000/v1")
    env["OPENAI_BASE_URL"] = base_url

    logger.info(f"🔧 Config: OPENAI_BASE_URL = {base_url}")

    # Pass optional target language to proxy via standard Header convention (converted to env var by some clients)
    # The python-gpt-po tool might not natively support custom headers, but if it uses httpx/requests
    # and we can trick it or if we are using a custom client wrapper, this helps.
    # ACTUAL FIX: The user requested adding this env var.
    env["HTTP_X_TARGET_LANG"] = os.environ.get("TARGET_LANG", "ja")

    return env


def find_po_files(input_dir: str) -> List[str]:
    """Recursively finds all .po files in the input directory."""
    return glob.glob(os.path.join(input_dir, "**/*.po"), recursive=True)


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
            # capture_output = True allows capturing stdout/stderr for logging
            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                return result

            logger.warning(
                f"Attempt {attempt + 1} failed with exit code {result.returncode}.")
            logger.warning(f"STDERR: {result.stderr}")

        except Exception as e:
            logger.error(f"Attempt {attempt + 1} raised exception: {e}")
            last_exception = e

        attempt += 1
        if attempt <= max_retries:
            wait_time = 2 ** attempt  # Exponential backoff: 2s, 4s
            logger.info(f"Retrying in {wait_time} seconds...")
            time.sleep(wait_time)

    if last_exception:
        raise last_exception
    else:
        raise Exception(f"Command failed after {max_retries} retries.")


def run_translation_workflow(model: str, input_base_dir: str, output_base_dir: str) -> None:
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
    logger.info(
        f"🚀 Found {total_files} files. Starting translation with model '{model}' for '{target_lang}'...")

    success_count = 0
    failure_count = 0

    env = get_env_config()

    logger.info(f"📁 Output will be written to: {output_base_dir}")

    # 3. Process Loop with Tempfile Context
    # We use a TemporaryDirectory to cleanly isolate each file processing
    try:
        with tempfile.TemporaryDirectory() as temp_work_dir:
            logger.info(f"Created temporary workspace at {temp_work_dir}")

            for index, src_file in enumerate(po_files, 1):
                rel_path = os.path.relpath(src_file, input_base_dir)
                filename = os.path.basename(src_file)
                final_dest_file = os.path.join(output_base_dir, rel_path)

                # Ensure final destination sub-directory exists
                os.makedirs(os.path.dirname(final_dest_file), exist_ok=True)

                logger.info(
                    f"[{index}/{total_files}] 📦 Processing: {rel_path}")

                try:
                    # A. ISOLATION STEP: Clear temp (should be empty, but good practice if reusing dir in loop logic)
                    # Since we reuse the SAME temp dir for performance (avoiding creating/destroying 1000 dirs),
                    # we must manually clear it.
                    for f in glob.glob(os.path.join(temp_work_dir, "*")):
                        os.remove(f)

                    temp_file_path = os.path.join(temp_work_dir, filename)
                    shutil.copy2(src_file, temp_file_path)

                    # B. PREPARE COMMAND
                    cmd = prepare_command(model, target_lang, temp_work_dir)

                    # C. EXECUTE
                    result = execute_translation(cmd, env)

                    # D. HANDLE RESULT
                    if result.returncode == 0:
                        if os.path.exists(temp_file_path):
                            shutil.copy2(temp_file_path, final_dest_file)
                            logger.info(f"   ✅ Saved to: {final_dest_file}")
                            success_count += 1
                        else:
                            logger.warning(
                                f"   ⚠️ Error: Output file missing in temp dir: {filename}")
                            logger.error(
                                f"File {filename} missing from {temp_work_dir} after successful run.")
                            failure_count += 1
                    else:
                        logger.error(
                            f"   ❌ Tool execution failed for {rel_path} (Exit Code: {result.returncode})")
                        failure_count += 1

                except Exception as e:
                    logger.critical(
                        f"   ❌ Critical Error on {rel_path}: {e}", exc_info=True)
                    failure_count += 1

    except Exception as e:
        logger.critical(
            f"Failed to create or manage temporary directory: {e}", exc_info=True)
        return

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

    args = parser.parse_args()

    run_translation_workflow(args.model, args.input, args.output)
