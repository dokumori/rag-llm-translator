"""
Unit Test: Glossary Extraction from DB
---------------------------------------
Tests the four-phase glossary extraction pipeline in
`services/toolbox/src/extract_glossary_from_db.py`.

All phases are tested in isolation using small, deterministic fixture data.
No ChromaDB connection is required — get_chroma_client is patched where needed.

Run Command:
    bin/run_tests.sh tests/unit/test_extract_glossary_from_db.py
"""
import csv
import os
import tempfile
import unittest
from collections import defaultdict
from unittest.mock import MagicMock, patch

import extract_glossary_from_db as eg


class TestIsSubstringMatch(unittest.TestCase):
    """Tests for the word-boundary substring matcher."""

    def test_exact_match(self):
        self.assertTrue(eg.is_substring_match("Browser", "ブラウザ", "Browser", "ブラウザ"))

    def test_case_insensitive_source(self):
        self.assertTrue(eg.is_substring_match("browser", "ブラウザ", "Browser settings", "ブラウザ settings"))

    def test_term_appears_in_longer_string(self):
        self.assertTrue(
            eg.is_substring_match("Action", "アクション", "Delete Action", "削除アクション")
        )

    def test_no_match_when_target_absent(self):
        self.assertFalse(
            eg.is_substring_match("Action", "アクション", "Delete Action", "削除")
        )

    def test_word_boundary_rejects_partial_word(self):
        # "Node" should NOT match inside "NodeJS"
        self.assertFalse(
            eg.is_substring_match("Node", "ノード", "NodeJS framework", "ノードJS")
        )

    def test_word_boundary_matches_whole_word(self):
        self.assertTrue(
            eg.is_substring_match("Node", "ノード", "Edit Node content", "ノードコンテンツ")
        )


class TestPhase1IdentifyCandidates(unittest.TestCase):

    def _make_records(self, entries):
        """Helper: list of (doc_text, metadata_dict) tuples."""
        return [(src, {"target": tgt, "msgctxt": ctx}) for src, tgt, ctx in entries]

    def test_accepts_one_word_term(self):
        records = self._make_records([("Browser", "ブラウザ", "")])
        candidates = eg._phase1_identify_candidates(records)
        self.assertIn(("browser", ""), candidates)

    def test_accepts_three_word_term(self):
        records = self._make_records([("Delete User Account", "ユーザーアカウント削除", "")])
        candidates = eg._phase1_identify_candidates(records)
        self.assertIn(("delete user account", ""), candidates)

    def test_rejects_four_word_term(self):
        records = self._make_records([("Delete All User Accounts", "全ユーザー削除", "")])
        candidates = eg._phase1_identify_candidates(records)
        self.assertNotIn(("delete all user accounts", ""), candidates)

    def test_rejects_term_over_50_chars(self):
        long_src = "A" * 51
        records = self._make_records([(long_src, "too long", "")])
        candidates = eg._phase1_identify_candidates(records)
        self.assertEqual(len(candidates), 0)

    def test_normalises_source_to_lowercase_key(self):
        records = self._make_records([("Browser", "ブラウザ", ""), ("browser", "ブラウザー", "")])
        candidates = eg._phase1_identify_candidates(records)
        # Both variations stored under the same lowercase key
        self.assertIn(("browser", ""), candidates)
        self.assertEqual(len(candidates[("browser", "")]), 2)

    def test_separates_by_context(self):
        records = self._make_records([
            ("Block", "ブロック", "Layout"),
            ("Block", "ブロック", "Content"),
        ])
        candidates = eg._phase1_identify_candidates(records)
        self.assertIn(("block", "Layout"), candidates)
        self.assertIn(("block", "Content"), candidates)

    def test_skips_empty_source_or_target(self):
        records = self._make_records([("", "target", ""), ("source", "", "")])
        candidates = eg._phase1_identify_candidates(records)
        self.assertEqual(len(candidates), 0)


class TestPhase2CountFrequencies(unittest.TestCase):

    def _make_records(self, entries):
        return [(src, {"target": tgt, "msgctxt": ctx}) for src, tgt, ctx in entries]

    def test_counts_correctly(self):
        records = self._make_records([
            ("Save", "保存", ""),
            ("Save changes", "変更を保存", ""),
            ("Save draft", "下書きを保存", ""),
        ])
        candidates = eg._phase1_identify_candidates(records)
        tallied = eg._phase2_count_frequencies(candidates, records)
        save_entry = next((t for t in tallied if t["src"] == "Save"), None)
        self.assertIsNotNone(save_entry)
        self.assertGreaterEqual(save_entry["count"], 2)

    def test_filters_below_min_occurrence(self):
        # Only one occurrence → should be filtered out
        records = self._make_records([("Rare", "まれ", "")])
        candidates = eg._phase1_identify_candidates(records)
        tallied = eg._phase2_count_frequencies(candidates, records)
        self.assertEqual(len(tallied), 0)

    def test_keeps_term_at_min_occurrence(self):
        records = self._make_records([
            ("Save", "保存", ""),
            ("Save draft", "下書きを保存", ""),
        ])
        candidates = eg._phase1_identify_candidates(records)
        tallied = eg._phase2_count_frequencies(candidates, records)
        # "Save" appears twice (once direct, once as substring) → should be kept
        self.assertTrue(any(t["src"] == "Save" for t in tallied))

    def test_empty_candidates_returns_empty(self):
        tallied = eg._phase2_count_frequencies({}, [])
        self.assertEqual(tallied, [])


class TestPhase3PruneSuperstrings(unittest.TestCase):

    def _make_term(self, src, tgt, msgctxt="", count=3):
        return {"key": src.lower(), "msgctxt": msgctxt, "src": src, "tgt": tgt, "count": count}

    def test_removes_compound_when_base_covers_it(self):
        terms = [
            self._make_term("Action", "アクション"),
            self._make_term("Action ID", "アクションID"),
        ]
        final_map = eg._phase3_prune_superstrings(terms)
        keys = [v["src"] for vals in final_map.values() for v in vals]
        self.assertIn("Action", keys)
        self.assertNotIn("Action ID", keys)

    def test_preserves_different_context_entries(self):
        terms = [
            self._make_term("Block", "ブロック", msgctxt="Layout"),
            self._make_term("Block content", "ブロックコンテンツ", msgctxt="Content"),
        ]
        final_map = eg._phase3_prune_superstrings(terms)
        keys = [v["src"] for vals in final_map.values() for v in vals]
        # Different contexts → no pruning
        self.assertIn("Block", keys)
        self.assertIn("Block content", keys)

    def test_preserves_unrelated_compounds(self):
        terms = [
            self._make_term("Node", "ノード"),
            self._make_term("Content type", "コンテンツタイプ"),
        ]
        final_map = eg._phase3_prune_superstrings(terms)
        keys = [v["src"] for vals in final_map.values() for v in vals]
        self.assertIn("Node", keys)
        self.assertIn("Content type", keys)


class TestPhase4WriteCsv(unittest.TestCase):

    def _make_final_map(self):
        """Minimal final_map compatible with _phase4_write_csv."""
        final_map = defaultdict(list)
        final_map[("browser", "")].append({
            "key": "browser", "msgctxt": "", "src": "Browser", "tgt": "ブラウザ", "count": 10
        })
        final_map[("save", "")].append({
            "key": "save", "msgctxt": "", "src": "Save", "tgt": "保存", "count": 5
        })
        return final_map

    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            eg._phase4_write_csv(self._make_final_map(), "ja", tmpdir)
            expected = os.path.join(tmpdir, "db_derived_glossary_ja.csv")
            self.assertTrue(os.path.exists(expected))

    def test_writes_correct_header(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            eg._phase4_write_csv(self._make_final_map(), "ja", tmpdir)
            with open(os.path.join(tmpdir, "db_derived_glossary_ja.csv"), newline="") as f:
                reader = csv.reader(f)
                header = next(reader)
            self.assertEqual(header, ["Source", "Context", "Target", "Total Occurrences", "Consistency", "Alternatives"])

    def test_writes_correct_row_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            final_map = defaultdict(list)
            final_map[("browser", "")].append({
                "key": "browser", "msgctxt": "", "src": "Browser", "tgt": "ブラウザ", "count": 10
            })
            eg._phase4_write_csv(final_map, "ja", tmpdir)
            with open(os.path.join(tmpdir, "db_derived_glossary_ja.csv"), newline="") as f:
                reader = csv.DictReader(f)
                row = next(reader)
            self.assertEqual(row["Source"], "Browser")
            self.assertEqual(row["Target"], "ブラウザ")
            self.assertEqual(row["Context"], "")
            self.assertEqual(row["Total Occurrences"], "10")
            self.assertEqual(row["Consistency"], "100.0%")
            self.assertEqual(row["Alternatives"], "")

    def test_sorts_alphabetically_by_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            eg._phase4_write_csv(self._make_final_map(), "ja", tmpdir)
            with open(os.path.join(tmpdir, "db_derived_glossary_ja.csv"), newline="") as f:
                reader = csv.DictReader(f)
                sources = [row["Source"] for row in reader]
            self.assertEqual(sources, sorted(sources))

    def test_handles_alternatives(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            final_map = defaultdict(list)
            final_map[("browser", "")].extend([
                {"key": "browser", "msgctxt": "", "src": "Browser", "tgt": "ブラウザ", "count": 8},
                {"key": "browser", "msgctxt": "", "src": "Browser", "tgt": "ブラウザー", "count": 2},
            ])
            eg._phase4_write_csv(final_map, "ja", tmpdir)
            with open(os.path.join(tmpdir, "db_derived_glossary_ja.csv"), newline="") as f:
                reader = csv.DictReader(f)
                row = next(reader)
            # Primary is the highest-count variant
            self.assertEqual(row["Target"], "ブラウザ")
            self.assertIn("ブラウザー", row["Alternatives"])


class TestExtractGlossaryForLanguage(unittest.TestCase):
    """End-to-end: phases 1–4 run together from a small fixture dataset."""

    FIXTURE_RECORDS = [
        # "Save" appears as both standalone and substring → frequency ≥ 2
        ("Save", {"target": "保存", "msgctxt": "", "langcode": "ja"}),
        ("Save changes", {"target": "変更を保存", "msgctxt": "", "langcode": "ja"}),
        ("Save draft", {"target": "下書きを保存", "msgctxt": "", "langcode": "ja"}),
        # "Browser" appears standalone only once → should be filtered out
        ("Browser", {"target": "ブラウザ", "msgctxt": "", "langcode": "ja"}),
    ]

    def test_produces_csv_for_language(self):
        records = [(src, meta) for src, meta in self.FIXTURE_RECORDS]
        with tempfile.TemporaryDirectory() as tmpdir:
            eg.extract_glossary_for_language(records, "ja", tmpdir)
            output_path = os.path.join(tmpdir, "db_derived_glossary_ja.csv")
            self.assertTrue(os.path.exists(output_path))

    def test_save_is_included_due_to_frequency(self):
        records = [(src, meta) for src, meta in self.FIXTURE_RECORDS]
        with tempfile.TemporaryDirectory() as tmpdir:
            eg.extract_glossary_for_language(records, "ja", tmpdir)
            with open(os.path.join(tmpdir, "db_derived_glossary_ja.csv"), newline="") as f:
                reader = csv.DictReader(f)
                sources = [row["Source"] for row in reader]
            self.assertIn("Save", sources)


class TestMain(unittest.TestCase):
    """Tests for the main() CLI entry point."""

    def _make_mock_collection(self, langcodes):
        col = MagicMock()
        docs = [f"term_{i}" for i in range(len(langcodes))]
        metas = [{"langcode": lc, "target": "t", "msgctxt": ""} for lc in langcodes]
        col.get.return_value = {"documents": docs, "metadatas": metas}
        return col

    @patch("extract_glossary_from_db.get_chroma_client")
    @patch("argparse.ArgumentParser.parse_args")
    def test_lang_flag_filters_to_single_language(self, mock_args, mock_client):
        mock_args.return_value = MagicMock(lang="ja", quiet=True)
        col = self._make_mock_collection(["ja", "ja", "it"])
        mock_client.return_value.get_collection.return_value = col

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RAG_ANALYSIS_DIR": tmpdir}):
                with patch("extract_glossary_from_db.extract_glossary_for_language") as mock_extract:
                    eg.main()
                    called_langs = [call[1]["langcode"] for call in mock_extract.call_args_list]
                    self.assertEqual(called_langs, ["ja"])

    @patch("extract_glossary_from_db.get_chroma_client")
    @patch("argparse.ArgumentParser.parse_args")
    def test_no_lang_flag_processes_all_languages(self, mock_args, mock_client):
        mock_args.return_value = MagicMock(lang=None, quiet=True)
        col = self._make_mock_collection(["ja", "it"])
        mock_client.return_value.get_collection.return_value = col

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RAG_ANALYSIS_DIR": tmpdir}):
                with patch("extract_glossary_from_db.extract_glossary_for_language") as mock_extract:
                    eg.main()
                    called_langs = sorted(
                        call[1]["langcode"] for call in mock_extract.call_args_list
                    )
                    self.assertEqual(called_langs, ["it", "ja"])

    @patch("extract_glossary_from_db.get_chroma_client")
    @patch("argparse.ArgumentParser.parse_args")
    def test_missing_collection_exits_with_error(self, mock_args, mock_client):
        mock_args.return_value = MagicMock(lang=None, quiet=True)
        mock_client.return_value.get_collection.side_effect = Exception("collection not found")

        with self.assertLogs("extract_glossary_from_db", level="ERROR") as log:
            with self.assertRaises(SystemExit) as cm:
                eg.main()
            self.assertEqual(cm.exception.code, 1)
            self.assertTrue(any("Could not find collection" in line for line in log.output))

    @patch("extract_glossary_from_db.get_chroma_client")
    @patch("argparse.ArgumentParser.parse_args")
    def test_lang_not_in_db_exits_with_error(self, mock_args, mock_client):
        mock_args.return_value = MagicMock(lang="fr", quiet=True)
        col = self._make_mock_collection(["ja"])
        mock_client.return_value.get_collection.return_value = col

        with self.assertLogs("extract_glossary_from_db", level="ERROR") as log:
            with self.assertRaises(SystemExit) as cm:
                eg.main()
            self.assertEqual(cm.exception.code, 1)
            self.assertTrue(any("not found in database" in line for line in log.output))


if __name__ == "__main__":
    unittest.main()
