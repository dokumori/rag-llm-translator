import sys
import os
import glob
import argparse
import importlib.util
import logging
from core.utils import find_po_files

logger = logging.getLogger(__name__)

def check_plugin_conflicts():
    """
    Ensure no plugin exists with the same name in both default and custom directories.
    """
    base_path = os.path.dirname(os.path.abspath(__file__))
    default_dir = os.path.join(base_path, "plugins", "default")
    custom_dir = os.path.join(base_path, "plugins", "custom")

    def get_plugin_names(directory):
        if not os.path.isdir(directory):
            return set()
        files = glob.glob(os.path.join(directory, "*.py"))
        return {os.path.splitext(os.path.basename(f))[0] for f in files if not f.endswith("__init__.py")}

    default_plugins = get_plugin_names(default_dir)
    custom_plugins = get_plugin_names(custom_dir)

    intersection = default_plugins.intersection(custom_plugins)
    if intersection:
        logger.error(
            "❌ Duplicate plugin names detected in 'default' and 'custom' directories: %s", intersection
        )
        logger.error("ℹ️ Plugin names must be globally unique. Please rename the custom plugin(s).")
        sys.exit(1)


def load_plugin(plugin_name):
    """
    Dynamically load a plugin module.
    Priority:
    1. services.toolbox.src.plugins.custom.<name>
    2. services.toolbox.src.plugins.default.<name>
    """
    base_path = os.path.dirname(os.path.abspath(__file__))
    
    # Paths to check
    custom_path = os.path.join(base_path, "plugins", "custom", f"{plugin_name}.py")
    default_path = os.path.join(base_path, "plugins", "default", f"{plugin_name}.py")
    
    target_path = None
    if os.path.exists(custom_path):
        target_path = custom_path
    elif os.path.exists(default_path):
        target_path = default_path
    else:
        logger.warning("⚠️ Plugin '%s' not found. Skipping.", plugin_name)
        return None

    try:
        spec = importlib.util.spec_from_file_location(plugin_name, target_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception as e:
        logger.error("❌ Failed to load plugin '%s': %s", plugin_name, e)
        return None

def resolve_plugins(lang: str | None = None) -> list[str]:
    """
    Resolve the plugin list for a specific language.

    Looks up POST_PROCESS_PLUGINS_<LANG>.  If no language is provided
    or no matching variable exists, returns an empty list (no plugins run).

    An explicitly empty value (e.g. POST_PROCESS_PLUGINS_ZH="") means
    "no plugins for this language".
    """
    if not lang:
        logger.info("ℹ️  No --lang provided. Cannot resolve plugins. Skipping.")
        return []

    # Normalise: "pt-br" → "PT_BR"
    env_key = f"POST_PROCESS_PLUGINS_{lang.upper().replace('-', '_')}"
    lang_specific = os.environ.get(env_key)

    if lang_specific is None:
        logger.info("ℹ️  No plugin config found for '%s' (%s). Skipping.", lang, env_key)
        return []

    plugins = [p.strip() for p in lang_specific.split(',') if p.strip()]
    if plugins:
        logger.info("🔌 Plugins for '%s': %s", lang, plugins)
    else:
        logger.info("ℹ️  Plugin config for '%s' is explicitly empty. No plugins to run.", lang)
    return plugins


def process_single_file(file_path: str, loaded_plugins: list) -> None:
    try:
        logger.info("🔧 Processing: %s...", os.path.basename(file_path))
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Run content through each loaded plugin sequentially
        for plugin in loaded_plugins:
            try:
                if hasattr(plugin, 'run'):
                    content = plugin.run(content)
                else:
                    logger.warning("⚠️ Plugin module does not have a 'run' function. Skipping.")
            except Exception as e:
                logger.error("❌ Error running plugin: %s", e)

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        logger.info("✅ Processed: %s", file_path)
    except Exception as e:
        logger.error("❌ Failed to process %s: %s", file_path, e)

def main():
    # --- Configuration ---
    check_plugin_conflicts()

    POST_PROCESS_INPUT_DIR = os.environ.get(
        "POST_PROCESS_INPUT_DIR", "/app/po/output")

    # Check if enabled
    enabled_str = os.environ.get("POST_PROCESSING_ENABLED", "true").lower()
    if enabled_str not in ("true", "1", "yes"):
        logger.info("ℹ️ Post-processing is disabled via environment variable. Skipping.")
        sys.exit(0)

    # Parse arguments
    parser = argparse.ArgumentParser(
        description="Post-process translated .po files using configurable plugins."
    )
    parser.add_argument(
        "input_path", nargs="?", default=None,
        help="Path to a .po file or directory of .po files."
    )
    parser.add_argument(
        "--lang", default=None,
        help="Target language code (e.g. ja, pt-br). "
             "Used to resolve language-specific plugin lists."
    )
    args = parser.parse_args()

    # Resolve plugins via precedence chain
    plugin_names = resolve_plugins(args.lang)
    if not plugin_names:
        logger.info("ℹ️ No plugins configured. Exiting.")
        sys.exit(0)

    loaded_plugins = []
    for name in plugin_names:
        module = load_plugin(name)
        if module:
            loaded_plugins.append(module)

    if not loaded_plugins:
        logger.warning("⚠️ No valid plugins loaded. Exiting.")
        sys.exit(0)

    # Input Path
    input_path = args.input_path
    if input_path is None:
        logger.warning("⚠️ No path provided. Defaulting to: %s", POST_PROCESS_INPUT_DIR)
        input_path = POST_PROCESS_INPUT_DIR

    files_to_process = []

    # Logic: Handle both specific files and directories
    if os.path.isfile(input_path):
        files_to_process.append(input_path)
    elif os.path.isdir(input_path):
        # Find all .po files in the folder (top level only) via shared utility
        files_to_process = find_po_files(input_path, recursive=False)
    else:
        logger.error("❌ Error: Path not found: %s", input_path)
        sys.exit(1)

    if not files_to_process:
        logger.warning("⚠️ No .po files found in %s", input_path)
        sys.exit(0)

    for po_file in files_to_process:
        process_single_file(po_file, loaded_plugins)

if __name__ == "__main__":
    main()
