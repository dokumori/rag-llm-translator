"""
Centralized language-aware path resolution.

All Python scripts MUST use these functions instead of hardcoding paths.
This ensures a single convention across the entire project:
    data/tm_source/{langcode}/
    data/translations/input/{langcode}/
    data/translations/output/{langcode}/
    data/translations/eval/{langcode}/
"""

import os

# Base directories — overridable via environment variables.
# Container defaults match the docker-compose volume mounts.
_TM_SOURCE_ROOT = os.environ.get("TM_SOURCE_ROOT",
                                  os.environ.get("TM_SOURCE_DIR", "/app/tm_source"))
_TRANSLATIONS_ROOT = os.environ.get("TRANSLATIONS_ROOT",
                                     os.environ.get("TRANSLATIONS_DIR", "/app/po"))


def tm_source_dir(langcode: str) -> str:
    """Returns the TM source directory for a given language."""
    return os.path.join(_TM_SOURCE_ROOT, langcode)


def glossary_path(langcode: str) -> str:
    """Returns the glossary CSV path for a given language."""
    return os.path.join(tm_source_dir(langcode), "glossary.csv")


def translation_input_dir(langcode: str) -> str:
    """Returns the translation input directory for a given language."""
    return os.path.join(_TRANSLATIONS_ROOT, "input", langcode)


def translation_output_dir(langcode: str) -> str:
    """Returns the translation output directory for a given language."""
    return os.path.join(_TRANSLATIONS_ROOT, "output", langcode)


def eval_dir(langcode: str, variant: str = "") -> str:
    """
    Returns the evaluation directory for a given language.
    
    Args:
        langcode: Target language code (e.g. 'ja', 'it').
        variant: Optional subdirectory (e.g. 'with_rag', 'without_rag').
    """
    base = os.path.join(_TRANSLATIONS_ROOT, "eval", langcode)
    return os.path.join(base, variant) if variant else base
