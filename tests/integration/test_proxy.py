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
embed_patcher = patch('chromadb.utils.embedding_functions.SentenceTransformerEmbeddingFunction')
MockEmbedding = embed_patcher.start()

# Now it is safe to import app
try:
  from app import app
except ImportError:
  # Fallback for local execution if paths are missing
  sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../services/rag-proxy/src')))
  from app import app

# Stop patcher to clean up, though likely irrelevant for ephemeral test process
embed_patcher.stop()
# ----------------------------------------------------------------------------

@pytest.fixture
def client():
  """Setup a temporary Flask test client."""
  app.testing = True
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
  mock_col_ref.name = "drupal_glossary"
  mock_chroma_client.return_value.list_collections.return_value = [mock_col_ref]

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

  print("\n----------------------------------------------------------------------")
  print("🧪 TEST: RAG Context Injection")
  
  client.post('/v1/chat/completions',
              data = json.dumps(payload),
              content_type = 'application/json')

  # 3. Verify Injection
  # We inspect the arguments passed to the mocked upstream client (OpenAI)
  # to ensure the system prompt was modified with the RAG data.
  call_args = mock_upstream_client.return_value.chat.completions.create.call_args
  assert call_args, "API was not called."

  _, kwargs = call_args
  sent_messages = kwargs.get('messages', [])
  
  system_message = next((m for m in sent_messages if m['role'] == 'system'), None)
  assert system_message, "No system message found in API call parameters."
  
  system_content = system_message['content']

  assert "Drupal Core" in system_content, "Glossary Source missing from prompt"
  assert "<glossary_matches>" in system_content, "XML tags missing from prompt"
  print("✅ CHECK PASSED: Glossary term and XML tags found in system prompt.")

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
                         data = json.dumps(payload),
                         content_type = 'application/json')

  mock_upstream_client.return_value.chat.completions.create.assert_not_called()
  print("🛡️  SAFETY CHECK PASSED: API Client was NOT called for dry run.")

  data = json.loads(response.data)
  assert data.get('id') == 'dry-run'
  print("✅ CHECK PASSED: Response ID indicated 'dry-run'.")

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
