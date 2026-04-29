"""
Unit Test: Ingestion Logic
--------------------------
Tests the glossary and TM ingestion functionality in `services/toolbox/src/ingest.py`.
Verifies file parsing, batching, and error handling.

Run Command:
    docker compose run --rm toolbox python -m pytest /app/tests/unit/test_ingest.py
"""
import ingest
import sys
import unittest
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path

# Adjusting sys.path to allow importing from services/toolbox/src
# This allows the test suite to find the 'ingest' module without installing it as a package.
# sys.path hacking removed per refactoring - rely on PYTHONPATH

# Importing the module under test


class TestIngest(unittest.TestCase):

    # --- 1. Utility Tests ---

    def test_generate_content_hash(self):
        """Verifies consistent MD5 hash generation."""
        # We use hashing to identify unique content batches in the database.
        text = "Hello World"
        hash1 = ingest.generate_content_hash(text)
        hash2 = ingest.generate_content_hash(text)

        # Consistent output for same input
        self.assertEqual(hash1, hash2)
        # Verify MD5 length
        self.assertEqual(len(hash1), 32)
        # Different output for different input
        self.assertNotEqual(
            hash1, ingest.generate_content_hash("Different"))

    def test_batch_generator(self):
        """Verifies correct chunking of lists."""
        data = [1, 2, 3, 4, 5]
        batches = list(ingest.batch_generator(data, n=2))
        self.assertEqual(batches, [[1, 2], [3, 4], [5]])

        batches_single = list(ingest.batch_generator(data, n=10))
        self.assertEqual(batches_single, [[1, 2, 3, 4, 5]])

    # --- 2. Glossary Processing Tests ---

    @patch("ingest.Path.exists")
    @patch("ingest.Path.glob")
    @patch("ingest.csv.DictReader")
    @patch("ingest.Path.open", new_callable=mock_open)
    @patch("ingest._ingest_batches")
    def test_process_glossary_deduplication(self, mock_ingest, mock_file, mock_dict_reader, mock_glob, mock_exists):
        """Verifies first-occurrence deduplication and batching trigger."""
        mock_exists.return_value = True
        mock_glob.return_value = [Path("glossary.csv")]  # Simulate finding one file

        # Include all columns that process_glossary normalises (source, target, context).
        # Deduplication key is (source, context), so both 'Apple' rows share the same key.
        mock_dict_reader.return_value = [
            {'source': 'Apple', 'target': 'Apfel',       'context': ''},
            {'source': 'Apple', 'target': 'Alternative', 'context': ''},  # duplicate key — skipped
            {'source': 'Orange', 'target': 'Apfelsine',  'context': ''}
        ]

        mock_client = MagicMock()
        mock_ef = MagicMock()

        # Pass a valid langcode string
        ingest.process_glossary(mock_client, mock_ef, "de")

        # Check deduplication: Apple should only have Apfel
        mock_ingest.assert_called_once()

        # Verify the batching function was called with the correct deduplicated data.
        # Arguments: collection, ids, documents, metadatas, batch_size, label
        call_args = mock_ingest.call_args[0]

        # Metadatas is at index 3
        metadata = call_args[3]

        self.assertEqual(len(metadata), 2)  # Apple, Orange
        self.assertEqual(metadata[0]['target'], 'Apfel')
        self.assertEqual(metadata[1]['target'], 'Apfelsine')

    @patch("ingest.Path.glob")
    def test_process_glossary_missing_file(self, mock_glob):
        """Verifies graceful handling of missing glossary file."""
        mock_glob.return_value = []  # No CSVs found
        mock_client = MagicMock()

        # Capture INFO logs now, not ERROR
        with self.assertLogs("ingest", level="INFO") as log:
            ingest.process_glossary(
                mock_client, MagicMock(), Path("dummy/glossary.csv"))
            
            # Check if ANY of the logs contain the expected string
            self.assertTrue(any("No glossary CSV found" in line for line in log.output), 
                            f"Expected message not found in logs: {log.output}")

    # --- 3. Translation Memory Processing Tests ---

    @patch("ingest.Path.exists")
    @patch("ingest.find_po_files")
    @patch("polib.pofile")
    @patch("ingest._ingest_batches")
    def test_process_tm_logic(self, mock_ingest, mock_polib, mock_find_po, mock_exists):
        """Verifies fuzzy filtering, msgid deduplication, and recursive search."""
        mock_exists.return_value = True

        mock_find_po.return_value = ["nested/test.po"]

        # Mock PO entries
        entry_save = MagicMock(msgid="Save", msgstr="Speichern", flags=[], msgctxt="")
        entry_save_dupe = MagicMock(msgid="Save", msgstr="Old", flags=[], msgctxt="")
        entry_fuzzy = MagicMock(msgid="Fuzzy", msgstr="Wait", flags=["fuzzy"], msgctxt="")

        mock_po = MagicMock()
        mock_po.__iter__.return_value = [
            entry_save, entry_save_dupe, entry_fuzzy]
        mock_polib.return_value = mock_po

        # Execute processing on the mocked directory
        mock_client = MagicMock()
        ingest.process_tm(mock_client, MagicMock(), "ja")

        mock_ingest.assert_called_once()

        # Verify arguments passed to existing batch ingestion logic
        # unpack arguments correctly.
        # ingest.py sig: _ingest_batches(collection, ids, documents, metadatas, ...)
        call_args = mock_ingest.call_args[0]
        # arg 0 is collection, arg 1 is ids, arg 2 is docs, arg 3 is metadata
        ids = call_args[1]
        docs = call_args[2]
        metadata = call_args[3]

        self.assertEqual(len(docs), 1)
        # Verify document content matches expectation
        self.assertEqual(docs[0], "Save")
        # Verify ID matches the hash of the content
        self.assertEqual(ids[0], ingest.generate_content_hash("Save", langcode="ja", msgctxt=""))
        self.assertEqual(metadata[0]['target'], "Speichern")

    # --- 4. Incremental Batching Tests ---

    def test_ingest_batches_incremental_skip(self):
        """Verifies that existing IDs are skipped and only new ones added."""
        mock_col = MagicMock()

        # We have 3 items, ID2 already exists
        ids = ["id1", "id2", "id3"]
        docs = ["doc1", "doc2", "doc3"]
        meta = [{"t": 1}, {"t": 2}, {"t": 3}]

        # Mock collection.get to say id2 exists
        mock_col.get.return_value = {"ids": ["id2"]}

        ingest._ingest_batches(mock_col, ids, docs, meta,
                               batch_size=10, label="Test")

        # Verify add was called only with id1 and id3
        mock_col.add.assert_called_once()
        added_ids = mock_col.add.call_args[1]['ids']
        self.assertEqual(added_ids, ["id1", "id3"])

    def test_ingest_batches_batching(self):
        """Verifies correct batching of large datasets."""
        mock_col = MagicMock()
        mock_col.get.return_value = {"ids": []}  # Nothing exists

        ids = [f"id_{i}" for i in range(10)]
        docs = [f"doc_{i}" for i in range(10)]
        meta = [{} for _ in range(10)]

        ingest._ingest_batches(mock_col, ids, docs, meta,
                               batch_size=4, label="Test")

        # 10 items / batch size 4 = 3 calls (4, 4, 2)
        self.assertEqual(mock_col.add.call_count, 3)

    # --- 5. Main Orchestration Tests ---
    # These tests verify that CLI arguments like --glossary-only or --reset
    # are correctly parsed and passed to the logic functions.

    @patch("ingest.argparse.ArgumentParser.parse_args")
    @patch("ingest.get_chroma_client")
    @patch("ingest.get_embedding_function")
    @patch("ingest.process_glossary")
    @patch("ingest.process_tm")
    @patch("ingest.pre_flight_check", return_value=True)
    def test_main_routing(self, mock_pre_flight, mock_tm, mock_gloss, mock_ef, mock_chroma, mock_args):
        """Verifies CLI flags correctly route to processors."""

        # Test Case 1: Glossary Only
        mock_args.return_value = MagicMock(
            glossary_only=True, tm_only=False, reset=False, reset_only=False, lang="ja")
        ingest.main()
        mock_gloss.assert_called_once()
        mock_tm.assert_not_called()

        mock_gloss.reset_mock()
        mock_tm.reset_mock()

        # Test Case 2: TM Only
        mock_args.return_value = MagicMock(
            glossary_only=False, tm_only=True, reset=False, reset_only=False, lang="ja")
        ingest.main()
        mock_gloss.assert_not_called()
        mock_tm.assert_called_once()

    @patch("ingest.argparse.ArgumentParser.parse_args")
    @patch("ingest.get_chroma_client")
    @patch("ingest.get_embedding_function")
    @patch("ingest.process_glossary")
    @patch("ingest.process_tm")
    @patch("ingest.pre_flight_check", return_value=True)
    def test_main_reset_flow(self, mock_pre_flight, mock_tm, mock_gloss, mock_ef, mock_chroma, mock_args):
        """Verifies that reset flag is passed down."""
        mock_args.return_value = MagicMock(
            glossary_only=False, tm_only=False, reset=True, reset_only=False, lang="ja")
        ingest.main()

        # Check that reset=True was passed to both
        self.assertTrue(mock_gloss.call_args[1]['reset'])
        self.assertTrue(mock_tm.call_args[1]['reset'])


if __name__ == "__main__":
    unittest.main()
