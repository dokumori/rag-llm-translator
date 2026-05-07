"""
HTTP client for the rag-proxy's ingestion API.

Delegates all embedding and ChromaDB operations to the rag-proxy over HTTP,
eliminating the need for sentence-transformers/PyTorch in the toolbox container.
"""

import logging
from typing import List, Dict, Any, Set
from urllib.parse import urljoin

import requests

logger = logging.getLogger(__name__)


class IngestClient:
    """Thin HTTP wrapper around the rag-proxy's /api/ingest/* endpoints."""

    def __init__(self, base_url: str, timeout: int = 120):
        """
        Args:
            base_url: The rag-proxy base URL (e.g. "http://rag-proxy:5000").
            timeout: HTTP request timeout in seconds. Embedding large batches
                     can take time, so the default is generous.
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Sends a POST request and returns the JSON response."""
        url = f"{self.base_url}{path}"
        resp = requests.post(url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def reset_collection(self, collection: str, langcode: str) -> None:
        """Deletes a collection or language-specific entries."""
        self._post("/api/ingest/reset", {
            "collection": collection,
            "langcode": langcode,
        })

    def check_existing_ids(self, collection: str, ids: List[str]) -> Set[str]:
        """Returns the set of IDs that already exist in the collection."""
        result = self._post("/api/ingest/check-ids", {
            "collection": collection,
            "ids": ids,
        })
        return set(result.get("existing_ids", []))

    def add_documents(
        self,
        collection: str,
        ids: List[str],
        documents: List[str],
        metadatas: List[Dict[str, Any]],
    ) -> int:
        """
        Embeds and stores documents. Returns the number of documents added.
        """
        result = self._post("/api/ingest/add", {
            "collection": collection,
            "ids": ids,
            "documents": documents,
            "metadatas": metadatas,
        })
        return result.get("added", 0)

    def _get(self, path: str) -> Dict[str, Any]:
        """Sends a GET request and returns the JSON response."""
        url = f"{self.base_url}{path}"
        resp = requests.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def list_languages(self) -> Dict[str, Any]:
        """Returns language codes found in the vector DB collections.

        Returns a dict with keys:
            glossary_langs (list[str]): Languages in the glossary collection.
            tm_langs (list[str]): Languages in the TM collection.
            all_langs (list[str]): Union of both, sorted.
        """
        return self._get("/api/ingest/languages")

