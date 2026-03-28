import sys
import os
import glob
import importlib.util

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
        print(f"❌ Error: Duplicate plugin names detected in 'default' and 'custom' directories: {intersection}")
        print("ℹ️ Plugin names must be globally unique. Please rename the custom plugin(s).")
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
        print(f"⚠️ Plugin '{plugin_name}' not found. Skipping.")
        return None

    try:
        spec = importlib.util.spec_from_file_location(plugin_name, target_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception as e:
        print(f"❌ Failed to load plugin '{plugin_name}': {e}")
        return None

def process_single_file(file_path, loaded_plugins):
    try:
        print(f"🔧 Processing: {os.path.basename(file_path)}...")
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Run content through each loaded plugin sequentially
        for plugin in loaded_plugins:
            try:
                if hasattr(plugin, 'run'):
                    content = plugin.run(content)
                else:
                    print(f"⚠️ Plugin module does not have a 'run' function. Skipping.")
            except Exception as e:
                 print(f"❌ Error running plugin: {e}")

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"✅ Processed: {file_path}")
    except Exception as e:
        print(f"❌ Failed to process {file_path}: {e}")

def main():
    # --- Configuration ---
    check_plugin_conflicts()

    POST_PROCESS_INPUT_DIR = os.environ.get(
        "POST_PROCESS_INPUT_DIR", "/app/po/output")

    # Check if enabled
    enabled_str = os.environ.get("POST_PROCESSING_ENABLED", "true").lower()
    if enabled_str not in ("true", "1", "yes"):
        print(f"ℹ️ Post-processing is disabled via environment variable. Skipping.")
        sys.exit(0)

    # Load Plugins
    plugin_names_env = os.environ.get("POST_PROCESS_PLUGINS", "spacing_around_drupal_variables,jp_en_spacing")
    if not plugin_names_env:
        print("ℹ️ No plugins configured. Exiting.")
        sys.exit(0)
        
    plugin_names = [p.strip() for p in plugin_names_env.split(',') if p.strip()]
    loaded_plugins = []
    
    print(f"🔌 Loading plugins: {plugin_names}")
    for name in plugin_names:
        module = load_plugin(name)
        if module:
            loaded_plugins.append(module)
            
    if not loaded_plugins:
        print("⚠️ No valid plugins loaded. Exiting.")
        sys.exit(0)

    # Input Path
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
        # Find all .po files in the folder (top level only)
        search_pattern = os.path.join(input_path, "*.po")
        files_to_process = glob.glob(search_pattern)
    else:
        print(f"❌ Error: Path not found: {input_path}")
        sys.exit(1)

    if not files_to_process:
        print(f"⚠️ No .po files found in {input_path}")
        sys.exit(0)

    for po_file in files_to_process:
        process_single_file(po_file, loaded_plugins)

if __name__ == "__main__":
    main()
