"""
Integration Test: Ingestion Pipeline via Rag-Proxy API
-------------------------------------------------------
Verifies the end-to-end ingestion flow:
  toolbox (IngestClient) → rag-proxy (/api/ingest/*) → ChromaDB

This test would have caught the missing sentence-transformers dependency
that unit tests (which mock everything) silently missed.

Run Command:
    bin/run_tests.sh --integration -k test_ingest_api
    # or directly:
    docker compose exec toolbox python -m pytest /app/tests/integration/test_ingest_api.py --run-integration -v
"""
import os
import pytest
import logging

from ingest_client import IngestClient
from ingest import generate_content_hash

logger = logging.getLogger(__name__)

# The rag-proxy URL as seen from inside the toolbox container.
RAG_PROXY_URL = os.environ.get("RAG_PROXY_URL", "http://rag-proxy:5000")

# Use a dedicated test collection name to avoid polluting real data.
TEST_GLOSSARY_COLLECTION = "test_ingest_glossary"
TEST_TM_COLLECTION = "test_ingest_tm"


@pytest.fixture
def ingest_client():
    """Returns an IngestClient pointed at the running rag-proxy."""
    return IngestClient(RAG_PROXY_URL)


@pytest.fixture(autouse=True)
def cleanup_test_collections(ingest_client):
    """Ensures test collections are cleaned up before and after each test."""
    # Pre-cleanup (in case a previous test run left orphan data)
    for col in [TEST_GLOSSARY_COLLECTION, TEST_TM_COLLECTION]:
        try:
            ingest_client.reset_collection(col, "all")
        except Exception:
            pass

    yield

    # Post-cleanup
    for col in [TEST_GLOSSARY_COLLECTION, TEST_TM_COLLECTION]:
        try:
            ingest_client.reset_collection(col, "all")
        except Exception:
            pass


class TestIngestAPIConnectivity:
    """Smoke tests: can the toolbox reach the rag-proxy ingestion endpoints?"""

    def test_reset_nonexistent_collection(self, ingest_client):
        """Reset on a collection that doesn't exist should succeed gracefully."""
        # Should not raise — the endpoint handles 'does not exist' cleanly.
        ingest_client.reset_collection("nonexistent_test_collection", "all")

    def test_check_ids_empty_collection(self, ingest_client):
        """Checking IDs on an empty/new collection should return an empty set."""
        existing = ingest_client.check_existing_ids(
            TEST_GLOSSARY_COLLECTION, ["id_that_does_not_exist"]
        )
        assert existing == set()


class TestIngestAPICRUD:
    """Full create → read → delete lifecycle via the rag-proxy API."""

    def test_add_and_verify_documents(self, ingest_client):
        """
        Adds documents, verifies they are persisted, then cleans up.
        This is the core test that validates the full embedding + storage path.
        """
        # --- 1. Add documents ---
        ids = [
            generate_content_hash("Save", langcode="de"),
            generate_content_hash("Cancel", langcode="de"),
        ]
        documents = ["Save", "Cancel"]
        metadatas = [
            {"target": "Speichern", "langcode": "de", "context": ""},
            {"target": "Abbrechen", "langcode": "de", "context": ""},
        ]

        added = ingest_client.add_documents(
            TEST_GLOSSARY_COLLECTION, ids, documents, metadatas
        )
        assert added == 2, f"Expected 2 documents added, got {added}"
        logger.info("✅ Successfully added 2 documents via rag-proxy API.")

        # --- 2. Verify persistence via check_existing_ids ---
        existing = ingest_client.check_existing_ids(
            TEST_GLOSSARY_COLLECTION, ids
        )
        assert existing == set(ids), (
            f"Expected all IDs to exist after add. Missing: {set(ids) - existing}"
        )
        logger.info("✅ All added IDs confirmed as existing.")

    def test_incremental_skip(self, ingest_client):
        """
        Adds documents, then verifies that check_existing_ids correctly
        identifies which are already present (enabling incremental loading).
        """
        existing_id = generate_content_hash("Existing", langcode="ja")
        new_id = generate_content_hash("New", langcode="ja")

        # Insert one document first
        ingest_client.add_documents(
            TEST_TM_COLLECTION,
            [existing_id],
            ["Existing"],
            [{"target": "既存", "langcode": "ja", "msgctxt": ""}],
        )

        # Check both IDs — only existing_id should be found
        found = ingest_client.check_existing_ids(
            TEST_TM_COLLECTION, [existing_id, new_id]
        )
        assert existing_id in found, "Pre-inserted ID should be found"
        assert new_id not in found, "New ID should NOT be found"
        logger.info("✅ Incremental ID check correctly distinguishes existing vs new.")

    def test_reset_by_langcode(self, ingest_client):
        """
        Adds documents for two languages, resets one, and verifies
        only the targeted language was removed.
        """
        id_de = generate_content_hash("Save", langcode="de")
        id_ja = generate_content_hash("Save", langcode="ja")

        # Add one doc for each language
        ingest_client.add_documents(
            TEST_GLOSSARY_COLLECTION,
            [id_de],
            ["Save"],
            [{"target": "Speichern", "langcode": "de", "context": ""}],
        )
        ingest_client.add_documents(
            TEST_GLOSSARY_COLLECTION,
            [id_ja],
            ["Save"],
            [{"target": "保存", "langcode": "ja", "context": ""}],
        )

        # Reset only 'de'
        ingest_client.reset_collection(TEST_GLOSSARY_COLLECTION, "de")

        # Verify: 'de' should be gone, 'ja' should remain
        found = ingest_client.check_existing_ids(
            TEST_GLOSSARY_COLLECTION, [id_de, id_ja]
        )
        assert id_de not in found, "'de' entry should have been deleted"
        assert id_ja in found, "'ja' entry should still exist"
        logger.info("✅ Language-specific reset correctly removed only 'de' entries.")

    def test_reset_all(self, ingest_client):
        """Resets the entire collection and verifies it's empty."""
        id1 = generate_content_hash("Term1", langcode="it")

        ingest_client.add_documents(
            TEST_TM_COLLECTION,
            [id1],
            ["Term1"],
            [{"target": "Termine1", "langcode": "it", "msgctxt": ""}],
        )

        # Full reset
        ingest_client.reset_collection(TEST_TM_COLLECTION, "all")

        # Collection should be gone or empty
        found = ingest_client.check_existing_ids(TEST_TM_COLLECTION, [id1])
        assert id1 not in found, "All entries should have been deleted"
        logger.info("✅ Full collection reset verified.")
