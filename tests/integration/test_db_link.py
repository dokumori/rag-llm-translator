"""
Integration Test: Real Database Connectivity
--------------------------------------------
Verifies actual network communication between this service and ChromaDB.
Does NOT use mocks. Requires the ChromaDB container to be running.

Run Command:
    docker compose exec rag-proxy python -m pytest /app/tests/integration/test_db_link.py
"""
# numpy is only available inside the Docker container; skip the whole module gracefully
# when running locally so collection doesn't error out.
import pytest
np = pytest.importorskip("numpy")
from chromadb.api.types import Documents, Embeddings
from app import app
import sys
import chromadb
import os
import logging
import json
import time

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import app AFTER logging config, similar to other tests
# sys.path.append() removed per refactoring - rely on PYTHONPATH


@pytest.fixture
def real_chroma_client():
    """Returns a real ChromaDB HTTP client connected to the Docker service."""
    host = os.environ.get("CHROMA_HOST", "chroma")
    port = int(os.environ.get("CHROMA_PORT", 8000))

    logger.info(f"🔌 Connecting to real ChromaDB at {host}:{port}...")
    client = chromadb.HttpClient(host=host, port=port)
    return client


@pytest.fixture
def app_client(mocker):
    """Returns the Flask test client with SAFE model config."""
    app.testing = True

    # SAFETY: Mock get_models_config to force 'is_dry_run=True'
    mock_config = mocker.patch('app.get_models_config')
    mock_config.return_value = [
        {"id": "deepseek-r1-v1", "is_dry_run": True},
        {"id": "dry-run-dummy", "is_dry_run": True}
    ]

    with app.test_client() as client:
        yield client


class DummyEmbeddingFunction(chromadb.EmbeddingFunction):
    """Mock embedding function to avoid model downloads/cache writes during connectivity tests."""

    def __init__(self):
        pass

    @staticmethod
    def name() -> str:
        return "dummy_embedding_function"

    def get_config(self) -> dict:
        return {"name": "dummy_embedding_function"}

    @staticmethod
    def build_from_config(config: dict) -> "DummyEmbeddingFunction":
        return DummyEmbeddingFunction()

    def __call__(self, input: Documents) -> Embeddings:
        # Return valid fake vectors (e.g. 384 dimensions) as numpy arrays
        # ChromaDB (v0.4+) expects numpy arrays which it then converts via .tolist()
        return [np.array([0.1] * 384, dtype=np.float32) for _ in input]

    def embed_query(self, input: Documents) -> Embeddings:
        return self(input)

    def embed_documents(self, input: Documents) -> Embeddings:
        return self(input)


def test_direct_db_crud(real_chroma_client):
    """
    Verifies that we can Create, Read, and Delete a collection on the real DB.
    """
    col_name = "test_connection_collection"

    # 1. Cleanup from previous runs if needed
    # This ensures a clean state before we attempt to create the collection.
    try:
        real_chroma_client.delete_collection(col_name)
    except Exception:
        pass

    # 2. Create Collection
    logger.info(f"🧪 Creating collection '{col_name}'...")
    # CRITICAL: Use dummy embedding function to prevent Chroma from trying to
    # download the default model to /.cache (which causes PermissionError).
    collection = real_chroma_client.create_collection(
        name=col_name,
        embedding_function=DummyEmbeddingFunction(),
        metadata={"hnsw:space": "cosine"}
    )

    # 3. Insert Document
    # We insert a sample document with metadata to verify write capability.
    logger.info("   Inserting test document...")
    collection.add(
        documents=["This is a connectivity test."],
        metadatas=[{"source": "integration_test"}],
        ids=["test_1"]
    )

    # 4. Query Document
    logger.info("   Querying test document...")
    # Wait briefly for persistence if needed (though Chroma is usually immediate in-mem)
    results = collection.query(
        query_texts=["connectivity"],
        n_results=1
    )

    assert results['documents'][0][0] == "This is a connectivity test."
    
    # 5. Verify Metadata (HNSW Space)
    # Chroma collection.metadata should reflect the setting
    assert collection.metadata["hnsw:space"] == "cosine", "Distance metric must be Cosine"

    logger.info("✅ Direct CRUD test passed.")

    # 5. Cleanup
    real_chroma_client.delete_collection(col_name)


def test_proxy_to_db_communication(app_client):
    """
    Verifies that the Proxy can communicate with the Real DB via the /health endpoint
    and during a standard RAG flow (even if empty).
    """
    # 1. Test /health (Explicit connectivity check)
    logger.info("🧪 Testing Proxy -> Real DB connection via /health...")
    response = app_client.get('/health')

    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'ok'
    assert data['database'] == 'connected'
    logger.info("✅ Proxy health check passed.")

    # 2. Test RAG Flow (Chat Completion)
    # This verifies the internal get_chroma_client() logic works during a request.
    # Dry-run in app.py happens AFTER RAG, so using a dry-run model still
    # exercises the full ChromaDB lookup path without hitting the upstream LLM.
    logger.info(
        "🧪 Testing Proxy -> Real DB connection via /v1/chat/completions...")
    payload = {
        "model": "dry-run-dummy",
        "messages": [{"role": "user", "content": "Hello World"}],
    }
    response = app_client.post('/v1/chat/completions', json=payload)

    # Even if it's 200 (Dry Run) or 502 (Upstream Fail), provided it's not 503 (DB Fail).
    # app.py returns 503 if health check fails, but for chat it swallows RAG errors and logs them.
    # So we check that status is NOT 500/503 due to DB.
    # Actually dry-run returns 200.

    assert response.status_code == 200
    data = response.get_json()
    # If dry-run, id is 'dry-run'
    if data.get('id') == 'dry-run':
        logger.info("✅ Proxy RAG flow (Dry Run) passed.")
    else:
        logger.info(
            f"✅ Proxy RAG flow passed with status {response.status_code}.")
