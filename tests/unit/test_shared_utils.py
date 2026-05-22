import argparse
import os

import pytest

from core.utils import find_po_files, langcode, optional_langcode


# ---------------------------------------------------------------------------
# langcode validator
# ---------------------------------------------------------------------------

class TestLangcode:
    """Unit tests for core.utils.langcode()."""

    @pytest.mark.parametrize("value", [
        "ja",        # 2-letter ISO 639-1
        "en",
        "fr",
        "zh",
        "fra",       # 3-letter ISO 639-2
        "deu",
        "por",
        "pt-br",     # region subtag (lowercase)
        "pt-BR",     # region subtag (uppercase — regex allows [a-zA-Z0-9])
        "zh-Hant",   # script subtag
        "zh-CN",
        "en-US",
        "az-AZ",
    ])
    def test_valid_langcodes_are_accepted(self, value: str):
        """langcode() must return the value unchanged for valid BCP-47 codes."""
        assert langcode(value) == value

    @pytest.mark.parametrize("value", [
        "jpa",       # 3 letters but not a real subtag — structurally matches,
        # so we only reject structural violations; content-level validation
        # is out of scope.  Keeping this here to document expected behaviour:
        # "jpa" IS accepted by the regex (3 lowercase letters).
    ])
    def test_three_letter_codes_are_accepted(self, value: str):
        """Three-letter codes matching the regex pattern are structurally valid."""
        assert langcode(value) == value

    @pytest.mark.parametrize("bad_value", [
        "",            # empty string
        "a",           # too short (< 2 letters)
        "ja_JP",       # underscore instead of hyphen
        "12345",       # digits only
        "with_rag",    # underscore, multiple segments
        "en-",         # trailing hyphen without subtag
        "-en",         # leading hyphen
        "EN",          # uppercase primary tag
        "pt-br-extra", # too many subtag segments
        "ja ",         # trailing whitespace
        " ja",         # leading whitespace
        "abcd",        # 4-letter primary tag (exceeds 3)
    ])
    def test_invalid_langcodes_raise_argument_type_error(self, bad_value: str):
        """langcode() must raise ArgumentTypeError for structurally invalid values."""
        with pytest.raises(argparse.ArgumentTypeError) as exc_info:
            langcode(bad_value)
        assert bad_value in str(exc_info.value) or "Invalid language code" in str(exc_info.value)

    def test_error_message_contains_example_codes(self):
        """The error message should hint at expected formats."""
        with pytest.raises(argparse.ArgumentTypeError) as exc_info:
            langcode("bad!")
        msg = str(exc_info.value)
        assert "ja" in msg or "pt-br" in msg or "zh-Hant" in msg


# ---------------------------------------------------------------------------
# optional_langcode validator
# ---------------------------------------------------------------------------

class TestOptionalLangcode:
    """Unit tests for core.utils.optional_langcode()."""

    def test_empty_string_passes_through(self):
        """optional_langcode('') must return '' without raising."""
        assert optional_langcode("") == ""

    @pytest.mark.parametrize("value", ["ja", "pt-br", "fra", "zh-Hant"])
    def test_valid_codes_pass_through(self, value: str):
        """optional_langcode() delegates to langcode() for non-empty values."""
        assert optional_langcode(value) == value

    @pytest.mark.parametrize("bad_value", ["jpa_wrong", "12345", "EN", "a"])
    def test_invalid_codes_raise_argument_type_error(self, bad_value: str):
        """optional_langcode() must still reject structurally invalid non-empty values."""
        with pytest.raises(argparse.ArgumentTypeError):
            optional_langcode(bad_value)


@pytest.fixture
def po_test_dir(tmp_path):
    """Set up a temporary directory structure for file discovery tests."""
    # 1. Top-level files
    (tmp_path / "test1.po").write_text("")
    (tmp_path / "test2.PO").write_text("")
    (tmp_path / "test3.txt").write_text("")

    # 2. Sub-directory files
    sub_dir = tmp_path / "subdir"
    sub_dir.mkdir()
    (sub_dir / "test4.Po").write_text("")
    (sub_dir / "test5.pO").write_text("")
    (sub_dir / "test6.csv").write_text("")

    return tmp_path


class TestCoreUtils:
    def test_find_po_files_top_level(self, po_test_dir):
        """Verify that non-recursive search only finds .po files at the top level and is case-insensitive."""
        files = find_po_files(str(po_test_dir), recursive=False)

        assert len(files) == 2
        # Should find .po and .PO files
        filenames = [os.path.basename(f) for f in files]
        assert "test1.po" in filenames
        assert "test2.PO" in filenames

    def test_find_po_files_recursive(self, po_test_dir):
        """Verify that recursive search finds .po files in subdirectories as well, ignoring non-po files."""
        files = find_po_files(str(po_test_dir), recursive=True)

        assert len(files) == 4
        filenames = [os.path.basename(f) for f in files]

        # Verify it found standard and all weirdly cased .po files
        assert "test1.po" in filenames
        assert "test2.PO" in filenames
        assert "test4.Po" in filenames
        assert "test5.pO" in filenames

        # Ensure it didn't pick up .txt or .csv
        assert "test3.txt" not in filenames
        assert "test6.csv" not in filenames
