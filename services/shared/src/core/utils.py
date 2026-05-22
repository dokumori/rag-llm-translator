import os
import re
import argparse
from typing import List

# Regex for BCP-47-style language codes
_LANGCODE_RE = re.compile(r'^[a-z]{2,3}(-[a-zA-Z0-9]{2,4})?$')


def langcode(value: str) -> str:
    """Argparse ``type=`` validator for BCP-47-style language codes.

    Accepted patterns: ja, en, fra, pt-br, zh-Hant
    Rejected patterns: jpa, 12345, with_rag, a, ''

    Raises:
        argparse.ArgumentTypeError: if *value* does not match the expected pattern.
    """
    if not _LANGCODE_RE.match(value):
        raise argparse.ArgumentTypeError(
            f"Invalid language code '{value}'. "
            "Expected format: 2-3 lowercase letters, optionally followed by "
            "a hyphen and 2-4 alphanumerics (e.g. ja, pt-br, zh-Hant)."
        )
    return value


def optional_langcode(value: str) -> str:
    """Like :func:`langcode`, but also accepts the empty string ``""``.

    Use this for optional ``--lang`` arguments that default to ``""`` and
    mean "no language filter", while still rejecting clearly invalid values
    like ``"jpa"`` or ``"12345"``.
    """
    if value == "":
        return value
    return langcode(value)


def find_po_files(directory: str, recursive: bool = False) -> List[str]:
    """
    Finds all .po files in the specified directory, handling case-insensitive extensions
    across all platforms (e.g., .po, .PO, .Po, .pO).
    
    Args:
        directory: The directory to search in.
        recursive: Whether to search subdirectories recursively.
        
    Returns:
        A sorted list of unique absolute paths to .po files.
    """
    found_files = []
    
    if recursive:
        for root, _, files in os.walk(directory):
            for file in files:
                if file.lower().endswith('.po'):
                    found_files.append(os.path.join(root, file))
    else:
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.is_file() and entry.name.lower().endswith('.po'):
                    found_files.append(entry.path)
                    
    return sorted(list(set(found_files)))
