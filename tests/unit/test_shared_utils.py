import argparse
import os

import pytest

from core.utils import find_po_files, langcode, optional_langcode, is_openai_reasoning_model, build_llm_call_kwargs


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


# ---------------------------------------------------------------------------
# is_openai_reasoning_model
# ---------------------------------------------------------------------------

class TestIsOpenAIReasoningModel:
    """Unit tests for core.utils.is_openai_reasoning_model()."""

    @pytest.mark.parametrize("model_id", [
        "o1",
        "o1-mini",
        "o1-preview",
        "o3",
        "o3-mini",
        "o4",
        "o4-mini",
        "gpt-5",
        "gpt-5-turbo",
        # Case-insensitive: identifiers can arrive with varied casing
        "O1",
        "O3-Mini",
        "GPT-5",
    ])
    def test_recognised_reasoning_models(self, model_id: str):
        """Models matching a known O-series prefix must return True."""
        assert is_openai_reasoning_model(model_id) is True

    @pytest.mark.parametrize("model_id", [
        "gpt-4o",
        "gpt-4-turbo",
        "gpt-3.5-turbo",
        "claude-3-opus",
        "claude-sonnet-4",
        "mistral-7b",
        "llama-3",
        "deepseek-v3",
        # Partial prefix matches that must NOT trigger — "o1" as a substring only
        "no1se",
        "tool1",
    ])
    def test_non_reasoning_models(self, model_id: str):
        """Standard chat models and unrelated model IDs must return False."""
        assert is_openai_reasoning_model(model_id) is False


# ---------------------------------------------------------------------------
# build_llm_call_kwargs
# ---------------------------------------------------------------------------

class TestBuildLlmCallKwargs:
    """Unit tests for core.utils.build_llm_call_kwargs()."""

    _MESSAGES = [{"role": "user", "content": "Hello"}]

    def test_standard_model_includes_temperature_and_max_tokens(self):
        """Standard (non-O-series) models must get temperature=0 and max_tokens."""
        kwargs = build_llm_call_kwargs("gpt-4o", self._MESSAGES, 1024)

        assert kwargs["model"] == "gpt-4o"
        assert kwargs["messages"] is self._MESSAGES
        assert kwargs["temperature"] == 0
        assert kwargs["max_tokens"] == 1024
        assert "max_completion_tokens" not in kwargs

    def test_o_series_model_omits_temperature_uses_max_completion_tokens(self):
        """O-series models must omit temperature and use max_completion_tokens."""
        kwargs = build_llm_call_kwargs("o3-mini", self._MESSAGES, 2048)

        assert kwargs["model"] == "o3-mini"
        assert kwargs["messages"] is self._MESSAGES
        assert "temperature" not in kwargs, "temperature must be absent for O-series models"
        assert kwargs["max_completion_tokens"] == 2048
        assert "max_tokens" not in kwargs

    def test_gpt5_family_treated_as_reasoning_model(self):
        """GPT-5 family must follow the same O-series rules."""
        kwargs = build_llm_call_kwargs("gpt-5-turbo", self._MESSAGES, 512)

        assert "temperature" not in kwargs
        assert kwargs["max_completion_tokens"] == 512
        assert "max_tokens" not in kwargs

    @pytest.mark.parametrize("model_id", ["o1", "o1-mini", "o3", "o4", "o4-mini"])
    def test_all_o_series_prefixes_omit_temperature(self, model_id: str):
        """Every recognised O-series prefix must trigger the reasoning-model code path."""
        kwargs = build_llm_call_kwargs(model_id, self._MESSAGES, 100)
        assert "temperature" not in kwargs
        assert "max_completion_tokens" in kwargs
        assert "max_tokens" not in kwargs

    def test_max_tokens_value_is_forwarded_correctly(self):
        """The max_tokens argument must be forwarded without modification."""
        for limit in [256, 4096, 16384]:
            kwargs = build_llm_call_kwargs("gpt-4-turbo", self._MESSAGES, limit)
            assert kwargs["max_tokens"] == limit

