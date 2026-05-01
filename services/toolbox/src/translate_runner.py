import os
import shutil
import argparse
import logging
import tempfile
from dataclasses import dataclass
from typing import Dict
from core.config import load_models_config
from core.utils import find_po_files
from core.token_tracker import TokenTracker, build_price_table_from_config
from po_translator import translate_po_file

# --- Logging Configuration ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)  # suppress verbose HTTP request lines
logger = logging.getLogger(__name__)

# Constants
MAX_RETRIES = 2
_bulk_size_raw = os.environ.get("BULK_SIZE", "15")
try:
    BULK_SIZE = int(_bulk_size_raw)
except ValueError:
    logging.getLogger(__name__).warning(
        "⚠️ BULK_SIZE env var '%s' is not a valid integer; defaulting to 15.", _bulk_size_raw
    )
    BULK_SIZE = 15




def get_env_config(target_lang: str = None, skip_rag: bool = False) -> Dict[str, str]:
    """Returns the environment configuration for the translation tool."""
    env = os.environ.copy()
    env["OPENAI_API_KEY"] = "dummy"

    # Allow override via environment variable, default to http://rag-proxy:5000/v1
    base_url = os.environ.get("OPENAI_BASE_URL", "http://rag-proxy:5000/v1")

    # Prefer explicitly-passed target_lang (from CLI arg) over env var.
    # This lets translate.sh pass the freshly-read .env value without
    # requiring a container restart/rebuild.
    if target_lang is None:
        target_lang = os.environ.get("TARGET_LANG")
    if not target_lang:
        raise ValueError(
            "❌ TARGET_LANG is not set. "
            "Set it in your .env file (e.g. TARGET_LANG=ja) and re-run."
        )

    # Encode target language in URL path so rag-proxy receives it per-request.
    # This follows the same pattern as skip_rag: the OpenAI SDK appends
    # /chat/completions after the base_url, so path segments survive intact.
    base_url = f"{base_url.rstrip('/')}/lang_{target_lang}"

    if skip_rag:
        # Append /skip_rag to path directly instead of a query parameter which breaks /models resolution
        base_url = f"{base_url.rstrip('/')}/skip_rag"

    env["OPENAI_BASE_URL"] = base_url
    # Also propagate as an env var so any child process sees the same value
    env["TARGET_LANG"] = target_lang

    logger.info(f"🔧 Config: OPENAI_BASE_URL = {base_url}")

    return env

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
    tracker: TokenTracker


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
        # Create a temporary working directory to isolate this file's translation
        with tempfile.TemporaryDirectory() as temp_work_dir:
            temp_file_path = os.path.join(temp_work_dir, filename)

            # Copy the original file to the temporary workspace
            shutil.copy2(src_file, temp_file_path)

            # Run the translation using the custom in-process driver
            ok = translate_po_file(
                file_path=temp_file_path,
                model=ctx.model,
                target_lang=ctx.target_lang,
                env=ctx.env,
                max_retries=MAX_RETRIES,
                bulk_size=BULK_SIZE,
                tracker=ctx.tracker,
            )

            if ok:
                if validate_output_file(temp_file_path):
                    try:
                        shutil.copy2(temp_file_path, final_dest_file)
                        logger.info(f"   ✅ Saved to: {final_dest_file}")
                        return True
                    except (PermissionError, OSError) as e:
                        logger.error(f"   ❌ Error copying file to destination {final_dest_file}: {e}")
                        return False
                else:
                    return False
            else:
                logger.error(f"   ❌ Translation failed for {filename}")
                return False

    except Exception as e:
        # Catch unexpected errors to prevent the entire pipeline from crashing
        logger.critical(f"   ❌ Critical Error on {filename}: {e}", exc_info=True)
        return False


def run_translation_workflow(model: str, input_base_dir: str, output_base_dir: str, model_slug: str, rag_mode: str, timestamp: str, skip_rag: bool = False, target_lang: str = None) -> None:
    """
    Main orchestration function for the translation workflow.
    """
    # Prefer explicitly-passed target_lang (from CLI arg) over env var so that
    # changing TARGET_LANG in .env takes effect immediately without container restart.
    if target_lang is None:
        target_lang = os.environ.get("TARGET_LANG")
    if not target_lang:
        raise ValueError(
            "❌ TARGET_LANG is not set. "
            "Set it in your .env file (e.g. TARGET_LANG=ja) and re-run."
        )
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

    env = get_env_config(target_lang=target_lang, skip_rag=skip_rag)
    logger.info(f"📁 Output will be written to: {output_base_dir}")

    success_count = 0
    failure_count = 0

    # Build tracker: pricing comes from models.json
    try:
        _models_cfg = load_models_config()
        _price_table = build_price_table_from_config(_models_cfg)
        _prompt_rate, _completion_rate = _price_table.get(model, (None, None))
    except Exception:
        _prompt_rate, _completion_rate = None, None
    tracker = TokenTracker(
        model=model,
        cost_per_1k_prompt=_prompt_rate,
        cost_per_1k_completion=_completion_rate,
    )

    ctx = TranslationContext(
        model=model,
        target_lang=target_lang,
        env=env,
        model_slug=model_slug,
        rag_mode=rag_mode,
        timestamp=timestamp,
        tracker=tracker,
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
    tracker.print_summary()
    usage_path = os.path.join(output_base_dir, f"token_usage_{timestamp}_{model_slug}.json")
    tracker.save(usage_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run translations on .po files")
    parser.add_argument("--model", required=True, help="LLM Model ID")
    parser.add_argument("--input", required=True, help="Input directory")
    parser.add_argument("--output", required=True, help="Output directory")
    parser.add_argument("--target-lang", default=None, help="Target language code (overrides TARGET_LANG env var)")
    parser.add_argument("--model-slug", required=True, help="Model slug for numbering")
    parser.add_argument("--rag-mode", required=True, help="RAG mode label")
    parser.add_argument("--timestamp", required=True, help="Run timestamp")
    parser.add_argument("--skip-rag", action="store_true", help="Bypass RAG semantic lookup entirely")

    args = parser.parse_args()

    run_translation_workflow(args.model, args.input, args.output, args.model_slug, args.rag_mode, args.timestamp, skip_rag=args.skip_rag, target_lang=args.target_lang)
