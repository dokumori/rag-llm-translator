# Post-Processing Logic

## Overview
In the `.po` files for Drupal core string translation, spaces between Japanese characters (multibyte) and English variables (ASCII) are often omitted. While Drupal can technically replace these variables without spaces, omitting them often leads to poor typographic rendering on the frontend (e.g., cramped text or line-breaking issues). I developed the `post_process.py` script to automatically insert these spacing standards for better readability.

## The Logic (Regex Rules)
The script parses the `.po` files and applies Regular Expressions (Regex) to the `msgstr` fields. It specifically targets Drupal variables, which are alphanumeric strings prefixed with `%`, `!`, or `@`.

To avoid modifying standard English sentences incorrectly, the script uses a "Multibyte Check". It only inserts spaces when the variable interacts with non-ASCII characters (like Japanese Kanji, Hiragana, or Katakana).

**The script enforces two specific rules:**

### Rule 1: Pre-Variable Spacing
If a multibyte character is immediately followed by a variable, a space is inserted.

* **Problem:** `エラーが発生しました%message`
* **Correction:** `エラーが発生しました %message`

### Rule 2: Post-Variable Spacing
If a variable is immediately followed by a multibyte character, a space is inserted.

* **Problem:** `%userさん、こんにちは`
* **Correction:** `%user さん、こんにちは`

## Scope & Limitations
It is important to note that this script currently **only** targets Drupal-specific variables. It does not wrap plain 1-byte alphanumeric characters (such as standard English words or isolated numbers) in whitespace.

* **Customisation:** If you find this specific variable formatting unnecessary, you can simply remove this step from the pipeline.
* **Enhancement:** Conversely, if you prefer consistent spacing around *all* English text within Japanese strings, the regex logic in this script would need to be enhanced to target all 1-byte alphanumeric characters, not just those with Drupal prefixes.

## Manual Usage
While the `translate_runner.py` script runs this automatically, you can also run the post-processor manually if you have edited `.po` files by hand or want to re-process an old batch.

You can target a specific file or an entire directory:

**Command:**
`docker compose exec toolbox python3 /app/src/post_process.py <path>`

**Example:**
`docker compose exec toolbox python3 /app/src/post_process.py /app/po/output/ja`

The script will output `✅ Fixed variables in: <filename>` for every file it modifies.
