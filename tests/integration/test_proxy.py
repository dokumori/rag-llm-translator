"""
Integration Tests for RAG Proxy Service (Pytest)
---------------------------------------

Key Features Tested:
1. RAG Context Injection: Verified via simulated ChromaDB responses.
2. Cost Safety (Dry Run): Verified via dry-run mode logic.
3. Health Checks: Verified via the /health endpoint.

Run Command:
    docker compose exec rag-proxy python -m pytest /app/tests/integration/test_proxy.py
"""
import pytest
import json
import sys
import os
from unittest.mock import MagicMock

# We must mock the Embedding Function BEFORE 'app' imports it,
# to prevent the 2GB model download during test collection/execution.
# In pytest, we can use sys.modules patching or just rely on 'mocker.patch'
# if we import inside the test/fixture, but since 'app' is global, we patch early.
from unittest.mock import patch
embed_patcher = patch(
    'chromadb.utils.embedding_functions.SentenceTransformerEmbeddingFunction')
MockEmbedding = embed_patcher.start()

# Now it is safe to import app
try:
    from app import app
except ImportError:
    # Fallback to rely on PYTHONPATH
    # sys.path.append() removed per refactoring
    from app import app

# Stop patcher to clean up, though likely irrelevant for ephemeral test process
embed_patcher.stop()
# ----------------------------------------------------------------------------


@pytest.fixture
def client(mocker):
    """Setup a temporary Flask test client with SAFE model config."""
    app.testing = True
    
    # SAFETY: Mock get_models_config to force 'is_dry_run=True' 
    # for the models used in tests, ensuring NO upstream costs.
    mock_config = mocker.patch('app.get_models_config')
    mock_config.return_value = [
        {"id": "deepseek-r1-v1", "is_dry_run": True},
        {"id": "claude-opus-4-5-20251101", "is_dry_run": True} 
    ]

    with app.test_client() as client:
        yield client


def test_rag_context_injection(client, mocker):
    """
    Test that RAG results are correctly formatted and injected into the System Prompt.
    """
    # 1. Setup Mock ChromaDB
    # We mock the ChromaDB client to simulate finding a collection and returning results
    # without needing a real database connection.
    mock_chroma_client = mocker.patch('app.get_chroma_client')
    mock_upstream_client = mocker.patch('app.get_upstream_client')

    # Mock List Collections
    mock_col_ref = MagicMock()
    mock_col_ref.name = "app_glossary"
    mock_chroma_client.return_value.list_collections.return_value = [
        mock_col_ref]

    # Mock Query Results
    mock_collection = MagicMock()
    mock_chroma_client.return_value.get_collection.return_value = mock_collection
    mock_collection.query.return_value = {
        'documents': [['Drupal Core']],
        'metadatas': [[{'target': 'Drupalコア'}]],
        'distances': [[0.1]]
    }

    # Mock OpenAI Response
    mock_response = MagicMock()
    mock_response.model_dump.return_value = {
        "choices": [{"message": {"content": "Translated"}}]
    }
    mock_upstream_client.return_value.chat.completions.create.return_value = mock_response

    # 2. Send Request
    # We send a standard translation request. The system should intercept this,
    # perform a RAG lookup (mocked above), and inject the context into the system prompt.
    payload = {
        "model": "deepseek-r1-v1",
        "messages": [{"role": "user", "content": "Text to translate:\nDrupal Core"}],
        "system": "You are a translator."
    }

    # Mock construct_system_prompt to verify injection
    # We use wraps=app.construct_system_prompt to keep original behavior if needed, 
    # but a simple mock is enough if we just check args.
    # However, app.py imports it. We need to patch it where it is used.
    # It is defined in app.py, so patch 'app.construct_system_prompt'.
    mock_construct = mocker.patch('app.construct_system_prompt', return_value="System Prompt Injected")

    # 2. Send Request
    # We send a standard translation request. 
    payload = {
        "model": "deepseek-r1-v1",
        "messages": [{"role": "user", "content": "Text to translate:\nDrupal Core"}],
        "system": "You are a translator."
    }

    print("\n----------------------------------------------------------------------")
    print("🧪 TEST: RAG Context Injection")

    client.post('/v1/chat/completions',
                data=json.dumps(payload),
                content_type='application/json')

    # 3. Verify Injection
    # Since Safety Mode (Dry Run) is active, upstream API is NOT called.
    # We verify integration by checking that construct_system_prompt received the RAG content.
    args, _ = mock_construct.call_args
    # signature: (original_system_data, rag_content, target_lang)
    # rag_content is 2nd arg (index 1)
    passed_rag_content = args[1]
    
    assert "Drupal Core" in passed_rag_content, "Glossary Source missing from RAG content arg"
    assert "<glossary_matches>" in passed_rag_content, "XML tags missing from RAG content arg"
    print("✅ CHECK PASSED: RAG content passed to prompt constructor.")


def test_dry_run_safety(client, mocker):
    """
    Test Safety Mechanism: The 'Dry Run' Model ID should NEVER hit the real API.
    """
    mock_upstream_client = mocker.patch('app.get_upstream_client')
    # Also mock Chroma to avoid DB connection errors during this test
    mocker.patch('app.get_chroma_client')

    print("\n----------------------------------------------------------------------")
    print("🧪 TEST: Dry Run Safety")

    payload = {
        "model": "claude-opus-4-5-20251101",
        "messages": [{"role": "user", "content": "Secret dry run request"}]
    }

    response = client.post('/v1/chat/completions',
                           data=json.dumps(payload),
                           content_type='application/json')

    mock_upstream_client.return_value.chat.completions.create.assert_not_called()
    print("🛡️  SAFETY CHECK PASSED: API Client was NOT called for dry run.")

    data = json.loads(response.data)
    assert data.get('id') == 'dry-run'
    print("✅ CHECK PASSED: Response ID indicated 'dry-run'.")


def test_default_model_is_dry_run(client, mocker):
    """
    Test that if no model is provided, the system defaults to the dry-run model.
    """
    mock_upstream_client = mocker.patch('app.get_upstream_client')
    mocker.patch('app.get_chroma_client')

    print("\n----------------------------------------------------------------------")
    print("🧪 TEST: Default Model (Missing ID) Safety")

    # Payload with NO 'model' key
    payload = {
        "messages": [{"role": "user", "content": "Test missing model ID"}]
    }

    response = client.post('/v1/chat/completions',
                           data=json.dumps(payload),
                           content_type='application/json')

    # Should NOT hit upstream because default should now be a dry-run model
    mock_upstream_client.return_value.chat.completions.create.assert_not_called()
    
    data = json.loads(response.data)
    assert data.get('id') == 'dry-run', f"Expected id='dry-run', got {data.get('id')}"
    print("✅ CHECK PASSED: Request with missing model ID correctly defaulted to Dry Run.")


def test_unknown_model_is_dry_run(client, mocker):
    """
    Test that if an unknown model is provided, the system defaults to the dry-run behavior.
    """
    mock_upstream_client = mocker.patch('app.get_upstream_client')
    mocker.patch('app.get_chroma_client')

    print("\n----------------------------------------------------------------------")
    print("🧪 TEST: Unknown Model Safety")

    # Payload with an unknown 'model' key
    payload = {
        "model": "this-model-does-not-exist",
        "messages": [{"role": "user", "content": "Test unknown model"}]
    }

    response = client.post('/v1/chat/completions',
                           data=json.dumps(payload),
                           content_type='application/json')

    # Should NOT hit upstream because unknown models default to dry run
    mock_upstream_client.return_value.chat.completions.create.assert_not_called()
    
    data = json.loads(response.data)
    assert data.get('id') == 'dry-run', f"Expected id='dry-run', got {data.get('id')}"
    print("✅ CHECK PASSED: Request with unknown model ID correctly defaulted to Dry Run.")


def test_empty_model_is_dry_run(client, mocker):
    """
    Test that if an empty model is provided, the system defaults to the dry-run behavior.
    """
    mock_upstream_client = mocker.patch('app.get_upstream_client')
    mocker.patch('app.get_chroma_client')

    print("\n----------------------------------------------------------------------")
    print("🧪 TEST: Empty Model Safety")

    # Payload with an empty 'model' key
    payload = {
        "model": "",
        "messages": [{"role": "user", "content": "Test empty model"}]
    }

    response = client.post('/v1/chat/completions',
                           data=json.dumps(payload),
                           content_type='application/json')

    # Should NOT hit upstream because empty models default to dry run
    mock_upstream_client.return_value.chat.completions.create.assert_not_called()
    
    data = json.loads(response.data)
    assert data.get('id') == 'dry-run', f"Expected id='dry-run', got {data.get('id')}"
    print("✅ CHECK PASSED: Request with empty model ID correctly defaulted to Dry Run.")


def test_health_check(client, mocker):
    """Test basic connectivity via the /health endpoint."""
    print("\n----------------------------------------------------------------------")
    print("🧪 TEST: Health Check (/health)")

    # Mock ChromaDB for a healthy response
    mock_chroma = mocker.patch('app.get_chroma_client')
    mock_chroma.return_value.heartbeat.return_value = True

    response = client.get('/health')

    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'ok'
    assert data['database'] == 'connected'
    print("✅ CHECK PASSED: /health returned 200 and status 'ok'.")
