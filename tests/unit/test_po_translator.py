"""
Unit Tests: po_translator
--------------------------
Tests for the custom .po file translation driver.

Run command:
    docker compose exec toolbox pytest /app/tests/unit/test_po_translator.py
"""
import json
import os
import sys
import pytest
from unittest.mock import MagicMock, patch

import polib

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/toolbox/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/shared/src")))

from po_translator import (
    translate_po_file,
    _process_batch,
    _parse_translations,
    _get_plural_count,
    _expand_entry,
    _Slot,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_po_file(tmp_path, entries, plural_forms_header=None):
    """
    Create a minimal .po file.

    ``entries`` is a list of (msgid, msgstr, msgctxt) tuples for singular entries.
    """
    po = polib.POFile()
    po.metadata = {"Content-Type": "text/plain; charset=utf-8"}
    if plural_forms_header:
        po.metadata["Plural-Forms"] = plural_forms_header
    for msgid, msgstr, msgctxt in entries:
        e = polib.POEntry(msgid=msgid, msgstr=msgstr)
        if msgctxt:
            e.msgctxt = msgctxt
        po.append(e)
    path = str(tmp_path / "test.po")
    po.save(path)
    return path


def _make_plural_po_file(tmp_path, entries, plural_forms_header=None):
    """
    Create a .po file with plural entries.

    ``entries`` is a list of dicts: {msgid, msgid_plural, msgstr_plural, msgctxt (opt)}.
    """
    po = polib.POFile()
    po.metadata = {"Content-Type": "text/plain; charset=utf-8"}
    if plural_forms_header:
        po.metadata["Plural-Forms"] = plural_forms_header
    for spec in entries:
        e = polib.POEntry(
            msgid=spec["msgid"],
            msgid_plural=spec["msgid_plural"],
            msgstr_plural=spec.get("msgstr_plural", {0: "", 1: ""}),
        )
        if spec.get("msgctxt"):
            e.msgctxt = spec["msgctxt"]
        po.append(e)
    path = str(tmp_path / "test_plural.po")
    po.save(path)
    return path


ENV = {"OPENAI_API_KEY": "dummy", "OPENAI_BASE_URL": "http://rag-proxy:5000/v1"}


# ---------------------------------------------------------------------------
# _get_plural_count
# ---------------------------------------------------------------------------

class TestGetPluralCount:
    def _po(self, plural_forms_header=None):
        po = polib.POFile()
        po.metadata = {"Content-Type": "text/plain; charset=utf-8"}
        if plural_forms_header:
            po.metadata["Plural-Forms"] = plural_forms_header
        return po

    def test_reads_nplurals_from_header(self):
        po = self._po("nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : 1);")
        assert _get_plural_count(po, "ru") == 3

    def test_header_takes_priority_over_lang_table(self):
        # Header says 3, table for "nl" says 2 — header wins
        po = self._po("nplurals=3; plural=...;")
        assert _get_plural_count(po, "nl") == 3

    def test_falls_back_to_lang_table(self):
        po = self._po()  # no Plural-Forms header
        assert _get_plural_count(po, "nl") == 2
        assert _get_plural_count(po, "ru") == 3
        assert _get_plural_count(po, "ja") == 1
        assert _get_plural_count(po, "ar") == 6

    def test_defaults_to_2_for_unknown_language(self):
        po = self._po()
        assert _get_plural_count(po, "xx") == 2

    def test_handles_bcp47_lang_tags(self):
        po = self._po()
        assert _get_plural_count(po, "nl-NL") == 2
        assert _get_plural_count(po, "pt_BR") == 2


# ---------------------------------------------------------------------------
# _expand_entry
# ---------------------------------------------------------------------------

class TestExpandEntry:
    def test_singular_entry_yields_one_slot(self):
        entry = polib.POEntry(msgid="Hello", msgstr="")
        slots = _expand_entry(entry, plural_count=2)
        assert len(slots) == 1
        assert slots[0].text == "Hello"
        assert slots[0].form_index is None
        assert slots[0].total_forms is None
        assert slots[0].entry is entry

    def test_plural_entry_expands_to_n_slots(self):
        entry = polib.POEntry(
            msgid="One file", msgid_plural="%d files", msgstr_plural={0: "", 1: ""}
        )
        slots = _expand_entry(entry, plural_count=2)
        assert len(slots) == 2
        assert slots[0].text == "One file"
        assert slots[0].form_index == 0
        assert slots[1].text == "%d files"
        assert slots[1].form_index == 1
        assert all(s.total_forms == 2 for s in slots)
        assert all(s.entry is entry for s in slots)

    def test_plural_slavic_expands_to_3_slots(self):
        entry = polib.POEntry(
            msgid="One file", msgid_plural="%d files", msgstr_plural={0: "", 1: "", 2: ""}
        )
        slots = _expand_entry(entry, plural_count=3)
        assert len(slots) == 3
        # form 0 → singular source, forms 1+ → plural source
        assert slots[0].text == "One file"
        assert slots[1].text == "%d files"
        assert slots[2].text == "%d files"

    def test_no_plural_for_japanese(self):
        entry = polib.POEntry(
            msgid="One file", msgid_plural="%d files", msgstr_plural={0: ""}
        )
        slots = _expand_entry(entry, plural_count=1)
        assert len(slots) == 1
        assert slots[0].text == "One file"


# ---------------------------------------------------------------------------
# _parse_translations
# ---------------------------------------------------------------------------

class TestParseTranslations:
    def test_clean_json_array(self):
        result = _parse_translations('["Hello", "World"]', expected_count=2)
        assert result == ["Hello", "World"]

    def test_json_buried_in_prose(self):
        content = 'Here are the translations:\n["Hola", "Mundo"]\nDone.'
        result = _parse_translations(content, expected_count=2)
        assert result == ["Hola", "Mundo"]

    def test_raises_on_missing_array(self):
        with pytest.raises(ValueError, match="No JSON array found"):
            _parse_translations("No brackets here at all.", expected_count=1)

    def test_raises_on_count_mismatch(self):
        with pytest.raises(ValueError, match="Expected 3 translations, got 2"):
            _parse_translations('["A", "B"]', expected_count=3)

    def test_coerces_non_strings_to_str(self):
        result = _parse_translations('[1, 2]', expected_count=2)
        assert result == ["1", "2"]

    def test_brackets_inside_translated_strings(self):
        """Brackets that are part of the translated text must not confuse the parser."""
        content = '["Hello [world]!", "See [note] below"]'
        result = _parse_translations(content, expected_count=2)
        assert result == ["Hello [world]!", "See [note] below"]

    def test_prose_with_brackets_before_array(self):
        """Square-bracket notation in LLM prose before the array must be skipped."""
        content = 'Here [note]: the translations are: ["foo", "bar"]'
        result = _parse_translations(content, expected_count=2)
        assert result == ["foo", "bar"]

    def test_prose_with_brackets_after_array(self):
        """Square-bracket notation in LLM prose after the array must be ignored."""
        content = '["foo", "bar"] See note [1] for details.'
        result = _parse_translations(content, expected_count=2)
        assert result == ["foo", "bar"]

    def test_brackets_before_and_after_array(self):
        """Brackets in prose both before and after the array are handled correctly."""
        content = '[context] ["Hola", "Mundo"] [done]'
        result = _parse_translations(content, expected_count=2)
        assert result == ["Hola", "Mundo"]


# ---------------------------------------------------------------------------
# _process_batch
# ---------------------------------------------------------------------------

class TestProcessBatch:
    @patch("po_translator.time.sleep")
    def test_success_returns_translations(self, _):
        client = MagicMock()
        client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='["Hola", "Mundo"]'))]
        )
        ok, translations = _process_batch(client, "model", ["Hello", "World"], "", max_retries=0)
        assert ok is True
        assert translations == ["Hola", "Mundo"]

    @patch("po_translator.time.sleep")
    def test_failure_returns_false_empty(self, _):
        client = MagicMock()
        client.chat.completions.create.side_effect = Exception("error")
        ok, translations = _process_batch(client, "model", ["Hello"], "", max_retries=0)
        assert ok is False
        assert translations == []

    @patch("po_translator.time.sleep")
    def test_retries_then_succeeds(self, mock_sleep):
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            Exception("transient"),
            MagicMock(choices=[MagicMock(message=MagicMock(content='["Hola"]'))]),
        ]
        ok, translations = _process_batch(client, "model", ["Hello"], "", max_retries=1)
        assert ok is True
        assert translations == ["Hola"]
        assert client.chat.completions.create.call_count == 2

    @patch("po_translator.time.sleep")
    def test_exhausts_all_retries(self, _):
        client = MagicMock()
        client.chat.completions.create.side_effect = Exception("persistent")
        ok, _ = _process_batch(client, "model", ["Hello"], "", max_retries=2)
        assert ok is False
        assert client.chat.completions.create.call_count == 3  # 1 + 2 retries

    @patch("po_translator.time.sleep")
    def test_payload_includes_context(self, _):
        client = MagicMock()
        client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='["Speichern"]'))]
        )
        _process_batch(client, "model", ["Save"], "button", max_retries=0)
        call_kwargs = client.chat.completions.create.call_args[1]
        user_content = call_kwargs["messages"][0]["content"]
        payload = json.loads(user_content[user_content.find("["):user_content.rfind("]") + 1])
        assert payload[0]["context"] == "button"
        assert payload[0]["text"] == "Save"

    @patch("po_translator.time.sleep")
    def test_no_nested_arrays_in_payload(self, _):
        """The flat-string approach must never embed nested arrays."""
        client = MagicMock()
        client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='["één bestand", "%d bestanden"]'))]
        )
        # Two slots: the expanded forms of a plural entry
        ok, translations = _process_batch(
            client, "model", ["One file", "%d files"], "", max_retries=0
        )
        assert ok is True
        assert translations == ["één bestand", "%d bestanden"]
        call_kwargs = client.chat.completions.create.call_args[1]
        user_content = call_kwargs["messages"][0]["content"]
        # Each payload item must be a plain string, not a list
        raw_start = user_content.find("[{")
        raw_payload = json.loads(user_content[raw_start:user_content.rfind("}]") + 2])
        for item in raw_payload:
            assert isinstance(item["text"], str)


# ---------------------------------------------------------------------------
# translate_po_file — end-to-end (OpenAI mocked)
# ---------------------------------------------------------------------------

class TestTranslatePoFile:
    @patch("po_translator.OpenAI")
    def test_skips_already_translated(self, mock_openai_cls, tmp_path):
        path = _make_po_file(tmp_path, [("Hello", "Hola", ""), ("World", "Mundo", "")])
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        ok = translate_po_file(path, "model", "es", ENV)
        assert ok is True
        mock_client.chat.completions.create.assert_not_called()

    @patch("po_translator.OpenAI")
    def test_translates_untranslated_singular_entries(self, mock_openai_cls, tmp_path):
        path = _make_po_file(tmp_path, [("Hello", "", ""), ("World", "", "")])
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='["Hola", "Mundo"]'))]
        )
        ok = translate_po_file(path, "model", "es", ENV, bulk_size=10)
        assert ok is True
        po = polib.pofile(path)
        assert po[0].msgstr == "Hola"
        assert po[1].msgstr == "Mundo"

    @patch("po_translator.OpenAI")
    def test_groups_by_context(self, mock_openai_cls, tmp_path):
        """Entries with different contexts must go into separate batches."""
        path = _make_po_file(tmp_path, [
            ("Save", "", "button"),
            ("Save", "", "menu"),
            ("Cancel", "", ""),
        ])
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='["Speichern"]'))]
        )
        translate_po_file(path, "model", "de", ENV, bulk_size=10)
        # 3 context groups → 3 separate API calls
        assert mock_client.chat.completions.create.call_count == 3

    @patch("po_translator.OpenAI")
    def test_saves_incrementally(self, mock_openai_cls, tmp_path):
        path = _make_po_file(tmp_path, [("A", "", ""), ("B", "", ""), ("C", "", "")])
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='["X"]'))]
        )
        with patch("polib.POFile.save") as mock_save:
            translate_po_file(path, "model", "de", ENV, bulk_size=1)
            assert mock_save.call_count == 3

    @patch("po_translator.OpenAI")
    def test_returns_false_on_invalid_po_file(self, mock_openai_cls, tmp_path):
        ok = translate_po_file(str(tmp_path / "nonexistent.po"), "model", "es", ENV)
        assert ok is False

    @patch("po_translator.OpenAI")
    def test_clears_fuzzy_flag_on_singular(self, mock_openai_cls, tmp_path):
        po = polib.POFile()
        po.metadata = {"Content-Type": "text/plain; charset=utf-8"}
        e = polib.POEntry(msgid="Hello", msgstr="")
        e.flags.append("fuzzy")
        po.append(e)
        path = str(tmp_path / "fuzzy.po")
        po.save(path)

        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='["Hola"]'))]
        )
        translate_po_file(path, "model", "es", ENV)
        assert "fuzzy" not in polib.pofile(path)[0].flags

    # -----------------------------------------------------------------------
    # Plural tests
    # -----------------------------------------------------------------------

    @patch("po_translator.OpenAI")
    def test_plural_entries_translated_end_to_end(self, mock_openai_cls, tmp_path):
        """
        Plural entries must be expanded, translated, and reassembled into
        msgstr_plural.  The LLM receives two flat strings and returns two flat
        strings; the driver collapses them back into the correct dict.
        """
        path = _make_plural_po_file(tmp_path, [{
            "msgid": "One file",
            "msgid_plural": "%d files",
            "msgstr_plural": {0: "", 1: ""},
        }])
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        # LLM receives ["One file", "%d files"] and returns two flat strings
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='["één bestand", "%d bestanden"]'))]
        )
        ok = translate_po_file(path, "model", "nl", ENV, bulk_size=10)
        assert ok is True
        po = polib.pofile(path)
        entry = po[0]
        assert entry.msgstr_plural[0] == "één bestand"
        assert entry.msgstr_plural[1] == "%d bestanden"
        assert entry.msgstr == ""

    @patch("po_translator.OpenAI")
    def test_plural_uses_nplurals_from_header(self, mock_openai_cls, tmp_path):
        """
        When Plural-Forms header specifies nplurals=3, three slots must be sent.
        """
        path = _make_plural_po_file(
            tmp_path,
            [{"msgid": "One file", "msgid_plural": "%d files",
              "msgstr_plural": {0: "", 1: "", 2: ""}}],
            plural_forms_header="nplurals=3; plural=(n%10==1 ? 0 : n%10>=2 && n%10<=4 ? 1 : 2);",
        )
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(
                content='["один файл", "%d файла", "%d файлов"]'
            ))]
        )
        ok = translate_po_file(path, "model", "ru", ENV, bulk_size=10)
        assert ok is True
        po = polib.pofile(path)
        assert po[0].msgstr_plural == {0: "один файл", 1: "%d файла", 2: "%d файлов"}

    @patch("po_translator.OpenAI")
    def test_plural_clears_fuzzy_flag(self, mock_openai_cls, tmp_path):
        po = polib.POFile()
        po.metadata = {"Content-Type": "text/plain; charset=utf-8"}
        e = polib.POEntry(
            msgid="One file", msgid_plural="%d files",
            msgstr_plural={0: "", 1: ""},
        )
        e.flags.append("fuzzy")
        po.append(e)
        path = str(tmp_path / "fuzzy_plural.po")
        po.save(path)

        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='["een bestand", "%d bestanden"]'))]
        )
        translate_po_file(path, "model", "nl", ENV)
        assert "fuzzy" not in polib.pofile(path)[0].flags

    @patch("po_translator.OpenAI")
    def test_mixed_singular_and_plural_same_batch(self, mock_openai_cls, tmp_path):
        """
        A batch may contain slots from both singular entries and plural entries.
        Singular results go to msgstr; plural results are collected and collapsed.
        """
        po = polib.POFile()
        po.metadata = {"Content-Type": "text/plain; charset=utf-8",
                       "Plural-Forms": "nplurals=2; plural=(n != 1);"}
        po.append(polib.POEntry(msgid="Cancel", msgstr=""))
        po.append(polib.POEntry(
            msgid="One result", msgid_plural="%d results",
            msgstr_plural={0: "", 1: ""},
        ))
        path = str(tmp_path / "mixed.po")
        po.save(path)

        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        # 3 slots: "Cancel", "One result", "%d results"
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(
                content='["Annuleren", "één resultaat", "%d resultaten"]'
            ))]
        )
        ok = translate_po_file(path, "model", "nl", ENV, bulk_size=10)
        assert ok is True
        po_reloaded = polib.pofile(path)
        assert po_reloaded[0].msgstr == "Annuleren"
        assert po_reloaded[1].msgstr_plural == {0: "één resultaat", 1: "%d resultaten"}
