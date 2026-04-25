import sys
import os
import subprocess
import shutil
import argparse
import logging
import tempfile
import time
from dataclasses import dataclass
from typing import List, Dict
from core.config import load_models_config
from core.utils import find_po_files

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

            # capture_output = set True to allow logging of stdout/stderr
            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True
            )
            
            last_result = result

            logger.info(f"Stdout: {result.stdout}")
            logger.info(f"Stderr: {result.stderr}")

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


def check_dry_run(model_id: str) -> bool:
    """Checks if the specified model is marked for dry run in the models config."""
    try:
        models_list = load_models_config()
        for m in models_list:
            if m["id"] == model_id:
                return bool(m.get("is_dry_run", False))
    except Exception as e:
        logger.warning(f"Could not read models config to check dry_run flag: {e}")
    return False


def generate_output_filepath(output_base_dir: str, original_filename: str, model_slug: str, rag_mode: str, timestamp: str) -> str:
    """Generates the final output filepath based on naming conventions."""
    basename_no_ext, ext = os.path.splitext(original_filename)
    new_filename = f"{basename_no_ext}_{model_slug}_{rag_mode}_{timestamp}{ext}"
    return os.path.join(output_base_dir, new_filename)


@dataclass
class TranslationContext:
    model: str
    target_lang: str
    env: Dict[str, str]
    model_slug: str
    rag_mode: str
    timestamp: str


def validate_output_file(file_path: str) -> bool:
    """Validates the translated output file exists and is not empty."""
    if not os.path.exists(file_path):
        logger.error(f"   ❌ Error: Output file is missing after successful run: {file_path}")
        return False
    if not os.path.isfile(file_path):
        logger.error(f"   ❌ Error: Output path is not a file: {file_path}")
        return False
    if os.path.getsize(file_path) == 0:
        logger.error(f"   ❌ Error: Output file is empty: {file_path}")
        return False
    return True


def process_single_file(src_file: str, output_base_dir: str, ctx: TranslationContext) -> bool:
    """Handles the translation process for a single file."""
    filename = os.path.basename(src_file)
    final_dest_file = generate_output_filepath(output_base_dir, filename, ctx.model_slug, ctx.rag_mode, ctx.timestamp)

    try:
        # Create a temporary working directory to isolate this file's
        # translation (which will be handled by gpt-po-translator)
        with tempfile.TemporaryDirectory() as temp_work_dir:
            temp_file_path = os.path.join(temp_work_dir, filename)
            
            # Copy the original file to the temporary workspace
            shutil.copy2(src_file, temp_file_path)

            # Prepare the shell command and execute the translation tool
            cmd = prepare_command(ctx.model, ctx.target_lang, temp_work_dir)
            result = execute_translation(cmd, ctx.env)

            # If the tool finished successfully, validate the results
            if result.returncode == 0:
                if validate_output_file(temp_file_path):
                    try:
                        # Move the translated file from the temp directory to the final output path
                        shutil.copy2(temp_file_path, final_dest_file)
                        logger.info(f"   ✅ Saved to: {final_dest_file}")
                        return True
                    except (PermissionError, OSError) as e:
                        logger.error(f"   ❌ Error copying file to destination {final_dest_file}: {e}")
                        return False
                else:
                    return False
            else:
                logger.error(f"   ❌ Tool execution failed for {filename} (Exit Code: {result.returncode})")
                return False

    except Exception as e:
        # Catch unexpected errors to prevent the entire pipeline from crashing
        logger.critical(f"   ❌ Critical Error on {filename}: {e}", exc_info=True)
        return False


def run_translation_workflow(model: str, input_base_dir: str, output_base_dir: str, model_slug: str, rag_mode: str, timestamp: str, skip_rag: bool = False) -> None:
    """
    Main orchestration function for the translation workflow.
    """
    target_lang = os.environ.get("TARGET_LANG", "ja")
    os.makedirs(output_base_dir, exist_ok=True)

    po_files = find_po_files(input_base_dir)
    if not po_files:
        logger.warning(f"⚠️ No .po files found in {input_base_dir}. No requests will be sent.")
        return

    total_files = len(po_files)
    is_dry_run = check_dry_run(model)
    
    # Note: is_dry_run only modifies the logging text in the current implementation.
    # The actual translation subprocess logic continues to execute as normal.
    if is_dry_run:
        logger.info(f"🚀 Found {total_files} files. Starting translation in Dry Run Mode for '{target_lang}'...")
    else:
        logger.info(f"🚀 Found {total_files} files. Starting translation with model '{model}' for '{target_lang}'...")

    env = get_env_config(skip_rag=skip_rag)
    logger.info(f"📁 Output will be written to: {output_base_dir}")

    success_count = 0
    failure_count = 0

    ctx = TranslationContext(
        model=model,
        target_lang=target_lang,
        env=env,
        model_slug=model_slug,
        rag_mode=rag_mode,
        timestamp=timestamp
    )

    for index, src_file in enumerate(po_files, 1):
        filename = os.path.basename(src_file)
        logger.info(f"[{index}/{total_files}] 📦 Processing: {filename}")
        
        success = process_single_file(src_file, output_base_dir, ctx)
        
        if success:
            success_count += 1
        else:
            failure_count += 1

    logger.info("=" * 30)
    logger.info("🎉 Translation run complete.")
    logger.info(f"📊 Summary: {success_count} Success, {failure_count} Failed, {total_files} Total")
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
