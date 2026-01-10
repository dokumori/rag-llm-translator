# Post-Processing Logic

## Overview
In the `.po` files for Drupal core string translation, spaces between Japanese characters (multibyte) and English variables (ASCII) are often omitted. While Drupal can technically replace these variables without spaces, omitting them often leads to poor typographic rendering on the frontend (e.g., cramped text or line-breaking issues). The `post_process.py` script was developed to automatically insert these spacing standards for better readability.

## The Logic (Regex Rules)
The script parses the `.po` files and applies Regular Expressions (Regex) to the `msgstr` fields, where translates strings are found. It specifically targets Drupal variables, which are alphanumeric strings prefixed with `%`, `!`, or `@`.

To avoid modifying standard English sentences incorrectly, the script uses a "Multibyte Check". It only inserts spaces when the variable interacts with non-ASCII characters (or, to be precise, the full-width, CKJ compatibility ideographs, for example Japanese Kanji and hiragana).

**The script enforces two specific rules:**

### Rule 1: Pre-Variable Spacing
If a multibyte character is immediately followed by a variable, a space is inserted.

* **w/o correction:** `エラーが発生しました%message`
* **w/ correction:** `エラーが発生しました %message`

### Rule 2: Post-Variable Spacing
If a variable is immediately followed by a multibyte character, a space is inserted.

* **w/o correction:** `%userさん、こんにちは`
* **w/ correction:** `%user さん、こんにちは`

## Scope & Limitations
It is important to note that this script currently **only** targets Drupal-specific variables. It does not wrap the words that consist of plain alphanumeric characters (or to be precise, half-width characters such as standard English words or isolated numbers) in whitespace.

If this specific variable formatting is found to be unnecessary, this step can be removed from the pipeline.Conversely, if consistent spacing is preferred around *all* English text within Japanese strings, the regex logic in this script can be enhanced to target words that consist of half-width characters, not just those with Drupal prefixes.

## Manual Usage
While the `translate_runner.py` script runs this automatically, the post-processor can also be run manually if `.po` files have been edited by hand or if re-processing of an old batch is required.

A specific file or an entire directory can be targeted:

**Command:**
`docker compose exec toolbox python3 /app/src/post_process.py <path>`

**Example:**
`docker compose exec toolbox python3 /app/src/post_process.py /app/po/output/ja`

The script will output `✅ Fixed variables in: <filename>` for every file it modifies.
