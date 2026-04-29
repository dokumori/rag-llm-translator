# Post-Processing Framework

The post-processing system is an extensible pipeline designed to clean, format, and standardise translated strings in `.po` files after the translation has been completed. It comes with two plugins by default, which are for formating Drupal strings into Japanese translations, but it also allows custom language rules and project-specific requirements through a plugin architecture.

---

## Configuration and Activation

Post-processing can be enabled/disabled via environment variables within your `.env` file. Plugins are always configured **per language** — there is no global plugin list.

### Quick Setup

The easiest way to configure post-processing is the interactive setup script:

```bash
bash bin/setup_post_processing.sh
```

This script will:
1. Scan available plugins from `plugins/default/` and `plugins/custom/`
2. Let you choose which plugins to enable for each language
3. Patch your `.env` file automatically

You can re-run it at any time to reconfigure.

### Environment Variables

| Variable | Description | Example |
| :--- | :--- | :--- |
| `POST_PROCESSING_ENABLED` | Global toggle to enable or disable the pipeline. | `true` |
| `POST_PROCESS_PLUGINS_<LANG>` | Comma-separated list of plugin names for a specific language. Use uppercased language code with hyphens as underscores (e.g., `JA`, `PT_BR`). | `spacing_around_drupal_variables,jp_en_spacing` |
| `POST_PROCESS_INPUT_DIR` | The directory where the runner looks for `.po` files to process. | `/app/po/output` |

### Manual `.env` Configuration

You can also edit `.env` directly instead of using the setup script:

```dotenv
POST_PROCESSING_ENABLED=true

# Japanese: run both Drupal variable spacing and Waou (和欧間) spacing
POST_PROCESS_PLUGINS_JA=spacing_around_drupal_variables,jp_en_spacing

# Spanish: run only Drupal variable spacing
POST_PROCESS_PLUGINS_ES=spacing_around_drupal_variables

# Chinese: explicitly skip all post-processing
POST_PROCESS_PLUGINS_ZH=
```

**Naming convention:** Uppercase the language code and replace hyphens with underscores (e.g., `pt-br` → `POST_PROCESS_PLUGINS_PT_BR`).

**Rules:**
- If `POST_PROCESS_PLUGINS_<LANG>` exists for the target language, those plugins run.
- If no variable exists for a language, no plugins run for that language.
- An explicitly empty value (e.g., `POST_PROCESS_PLUGINS_ZH=`) also means no plugins run.

---

## Plugin Architecture

The system uses a **Pipeline Pattern**. Each plugin is a standalone Python module that performs a specific text transformation.

### Execution Order

The execution order of the plugins is strictly sequential. They are executed in the exact order they are listed in the configuration (e.g., in `POST_PROCESS_PLUGINS_<LANG>`). If a transformation relies on the results of a previous one, ensure they are ordered appropriately.

### Plugin Discovery and Conflict Resolution

The runner identifies plugins by scanning two distinct directories:
1. **Custom Plugins**: `services/toolbox/src/plugins/custom/`
2. **Default Plugins**: `services/toolbox/src/plugins/default/`

To maintain predictability and prevent configuration errors, the system enforces a **Global Uniqueness Rule**. A plugin name (determined by its filename without the `.py` extension) must not exist in both directories simultaneously.

#### Conflict Handling

If a naming collision occurs — for instance, if `jp_en_spacing.py` exists in both the `default` and `custom` folders—the post-processing runner will immediately terminate with an error message. This prevents ambiguity regarding which logic is being applied.


### Default Plugins Included

* **`spacing_around_drupal_variables`**: Ensures Drupal variables (`%`, `!`, `@`) are separated from multibyte characters (such as Kanji or Hiragana) by a half-width space.
* **`jp_en_spacing`**: Implements "Waou" spacing (和欧間), inserting spaces between Japanese and Alphanumeric characters while respecting specific exception rules for punctuation and units.

### Creating Custom Plugins
To add a new feature, create a `.py` file in `services/toolbox/src/plugins/custom/`. The file **must** contain a `run` function:

```python
import re

def run(text):
    # Your custom logic here
    # Example: change 'Apple' to 'Orange' in all msgstr
    return re.sub(r'msgstr "Apple"', r'msgstr "Orange"', text)
```

---

## Testing Framework

Tests are built using `pytest` and are structured to allow isolated testing of core logic and user extensions.

### Core Tests

Located in `tests/unit/plugins/`, these verify the logic of the default plugins provided with the framework.

### Custom Tests

If you write custom plugins, you should write matching tests to ensure your regular expression rules do not break existing translations.
* **Storage Location**: `tests/custom/`.
* **Git Status**: This directory is ignored by Git (except for `.gitkeep`), ensuring your project-specific tests remain local to your environment.

### Running Tests

You can execute all tests using the provided helper script:

```bash
bash bin/run_tests.sh
```

---

## Manual Execution

If you have manually edited `.po` files and want to re-run the post-processing pipeline without re-translating the entire project, use the following command:

**Command:**
```bash
docker compose exec toolbox python3 /app/src/post_process.py <path> [--lang <langcode>]
```

**Example:**
```bash
docker compose exec toolbox python3 /app/src/post_process.py /app/po/output/ja --lang ja
```
