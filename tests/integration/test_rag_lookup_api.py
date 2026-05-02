"""
Integration Test: RAG Lookup API via Rag-Proxy
------------------------------------------------
Verifies the end-to-end RAG context retrieval flow:
  toolbox → rag-proxy (/api/rag-lookup) → ChromaDB → context returned

Tests ingest data first via /api/ingest/add, then query it via /api/rag-lookup
to confirm the full pipeline works without importing the rag-proxy's app module.

Run Command:
    bin/run_tests.sh --integration -k test_rag_lookup_api
    # or directly:
    docker compose exec toolbox python -m pytest /app/tests/integration/test_rag_lookup_api.py --run-integration -v
"""
import os
import pytest
import logging

from ingest_client import IngestClient
from ingest import generate_content_hash

import requests

logger = logging.getLogger(__name__)

RAG_PROXY_URL = os.environ.get("RAG_PROXY_URL", "http://rag-proxy:5000")


@pytest.fixture
def ingest_client():
    return IngestClient(RAG_PROXY_URL)


def rag_lookup(items, target_lang=""):
    """Helper: calls the /api/rag-lookup endpoint."""
    resp = requests.post(
        f"{RAG_PROXY_URL}/api/rag-lookup",
        json={"items": items, "target_lang": target_lang},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


class TestRagLookupAPIConnectivity:
    """Smoke tests: the endpoint is reachable and handles edge cases."""

    # Use a langcode that will never have ingested data, ensuring these tests
    # are isolated from whatever production data sits in app_glossary / app_tm.
    EMPTY_LANG = "zz_empty_test"

    def test_returns_empty_context_when_no_data(self):
        """With no ingested data, the endpoint should return an empty context string."""
        result = rag_lookup(
            [{"text": "Hello", "context": ""}],
            target_lang=self.EMPTY_LANG,
        )

        assert "rag_context" in result
        assert "matches" in result
        # No data ingested for this langcode → context should be empty
        assert result["rag_context"].strip() == ""

    def test_rejects_empty_items(self):
        """Sending an empty items list should return a 400 error."""
        resp = requests.post(
            f"{RAG_PROXY_URL}/api/rag-lookup",
            json={"items": []},
            timeout=10,
        )
        assert resp.status_code == 400

    def test_multiple_items_in_single_request(self):
        """The endpoint should accept multiple items in one request."""
        result = rag_lookup(
            [
                {"text": "Save", "context": ""},
                {"text": "Cancel", "context": ""},
                {"text": "Delete", "context": ""},
            ],
            target_lang=self.EMPTY_LANG,
        )

        assert "rag_context" in result
        assert isinstance(result["matches"], list)


class TestRagLookupAPIWithData:
    """
    Tests that require seeded data. Uses the ingest API to insert test entries
    into the real glossary/TM collections, then queries via /api/rag-lookup.

    NOTE: These tests use the production collection names (app_glossary, app_tm)
    because perform_rag_lookup is hard-wired to query those. The test data uses
    a unique langcode ('test_xx') to avoid interfering with real data, and is
    cleaned up after each test.
    """

    LANG = "test_xx"  # Unique langcode unlikely to conflict with real data

    @pytest.fixture(autouse=True)
    def seed_and_cleanup(self, ingest_client):
        """Seeds test data into the production collections with a unique langcode."""
        # Seed glossary
        glossary_id = generate_content_hash("Drupal", langcode=self.LANG)
        ingest_client.add_documents(
            "app_glossary",
            [glossary_id],
            ["Drupal"],
            [{"target": "ドルーパル", "source_original": "Drupal",
              "langcode": self.LANG, "context": ""}],
        )

        # Seed TM
        tm_id = generate_content_hash("Save changes", langcode=self.LANG)
        ingest_client.add_documents(
            "app_tm",
            [tm_id],
            ["Save changes"],
            [{"target": "変更を保存", "file": "test.po",
              "langcode": self.LANG, "msgctxt": ""}],
        )

        yield

        # Cleanup: remove only our test entries via the same IngestClient
        for col_name in ["app_glossary", "app_tm"]:
            try:
                ingest_client.reset_collection(col_name, self.LANG)
            except Exception:
                pass

    def test_glossary_match_returned(self):
        """Querying a seeded glossary term should return matching context."""
        result = rag_lookup(
            [{"text": "Drupal", "context": ""}],
            target_lang=self.LANG,
        )

        assert result["rag_context"].strip() != "", (
            "Expected non-empty RAG context for a seeded glossary term"
        )
        assert "ドルーパル" in result["rag_context"], (
            "Expected the Japanese glossary target in the context"
        )
        logger.info("✅ Glossary match correctly returned via /api/rag-lookup.")

    def test_tm_match_returned(self):
        """Querying a seeded TM entry should return matching context."""
        result = rag_lookup(
            [{"text": "Save changes", "context": ""}],
            target_lang=self.LANG,
        )

        assert result["rag_context"].strip() != "", (
            "Expected non-empty RAG context for a seeded TM entry"
        )
        assert "変更を保存" in result["rag_context"], (
            "Expected the Japanese TM target in the context"
        )
        logger.info("✅ TM match correctly returned via /api/rag-lookup.")

    def test_no_cross_language_bleed(self):
        """Querying with a different langcode should NOT return our test data."""
        result = rag_lookup(
            [{"text": "Drupal", "context": ""}],
            target_lang="zz_nonexistent",
        )

        # The context should not contain our test_xx entries
        assert "ドルーパル" not in result.get("rag_context", ""), (
            "Test data for 'test_xx' should not appear when querying 'zz_nonexistent'"
        )
        logger.info("✅ No cross-language bleed confirmed.")

    def test_match_log_structure(self):
        """The matches list should contain structured log entries."""
        result = rag_lookup(
            [{"text": "Drupal", "context": ""}],
            target_lang=self.LANG,
        )

        matches = result.get("matches", [])
        assert len(matches) > 0, "Expected at least one match log entry"

        match = matches[0]
        assert "type" in match  # 'glossary' or 'tm'
        assert "dist" in match  # distance score
        assert "accepted" in match  # whether it passed the guardrail
        logger.info("✅ Match log structure is correct.")
