"""
Integration Tests for RAG Proxy Service
---------------------------------------
This suite tests the `rag-proxy` Flask application (app.py).

Key Features Tested:
1. RAG Context Injection: 
   - Mocks ChromaDB to return a fake Glossary match ("Drupal Core").
   - Mocks the OpenAI-compatible upstream client to avoid real costs.
   - Verifies that the 'system prompt' sent to the LLM actually contains
     the data retrieved from ChromaDB (the RAG pattern).

2. Cost Safety (Dry Run):
   - Ensures that using the specific "Dry Run" model ID triggers a mock response
     internally and strictly *prevents* the code from calling the real paid API.

3. Health Checks:
   - Verifies the server responds to basic ping requests.

Usage:
  Execute inside the 'rag-proxy' container:
  $ python3 -m unittest /app/tests/integration/test_proxy.py

  or

  docker compose run --rm \
  -v "$(pwd)/tests:/app/tests" \
  -v "$(pwd)/services/rag-proxy:/app/services/rag-proxy" \
  rag-proxy python3 -m unittest /app/tests/integration/test_proxy.py
"""
import unittest
from unittest.mock import patch, MagicMock
import json
import sys
import os

# --- 🚀 PERFORMANCE FIX -----------------------------------------------------
# Patch the Embedding Function BEFORE importing 'app' to prevent 2GB download.
embed_patcher = patch('chromadb.utils.embedding_functions.SentenceTransformerEmbeddingFunction')
MockEmbedding = embed_patcher.start()

# Point to services/rag-proxy/src to import the Flask app
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../services/rag-proxy/src')))
from app import app

# Stop the patcher so it doesn't leak
embed_patcher.stop()
# ----------------------------------------------------------------------------

class TestRAGProxy(unittest.TestCase):

  def setUp(self):
    """Setup a temporary Flask test client for every test."""
    self.app = app.test_client()
    self.app.testing = True

  @patch('app.chroma_client')
  @patch('app.upstream_client')
  def test_rag_context_injection(self, mock_openai, mock_chroma):
    """
    Test that RAG results are correctly formatted and injected into the System Prompt.
    """
    # 1. Setup Mock ChromaDB (List Collections)
    # app.py checks if collections exist first. We mock this check.
    mock_col_ref = MagicMock()
    mock_col_ref.name = "drupal_glossary"
    mock_chroma.list_collections.return_value = [mock_col_ref]

    # 2. Setup Mock ChromaDB (Query Results)
    mock_collection = MagicMock()
    mock_chroma.get_collection.return_value = mock_collection
    mock_collection.query.return_value = {
      'documents': [['Drupal Core']],
      'metadatas': [[{'target': 'Drupalコア'}]],
      'distances': [[0.1]] 
    }

    # 3. Setup Mock OpenAI Response
    mock_response = MagicMock()
    mock_response.model_dump.return_value = {
        "choices": [{"message": {"content": "Translated"}}]
    }
    mock_openai.chat.completions.create.return_value = mock_response

    # 4. Send Request
    payload = {
      "model": "deepseek-r1-v1",
      "messages": [{"role": "user", "content": "Text to translate:\nDrupal Core"}],
      "system": "You are a translator."
    }

    print("\n----------------------------------------------------------------------")
    print("🧪 TEST: RAG Context Injection")
    
    self.app.post('/v1/chat/completions',
                  data=json.dumps(payload),
                  content_type='application/json')

    # 5. Verify Injection
    try:
      call_args = mock_openai.chat.completions.create.call_args
      if not call_args:
        self.fail("API was not called.")

      _, kwargs = call_args
      sent_messages = kwargs.get('messages', [])
      
      system_message = next((m for m in sent_messages if m['role'] == 'system'), None)
      if not system_message:
          self.fail("No system message found in API call parameters.")
      
      system_content = system_message['content']

      self.assertIn("Drupal Core", system_content, "Glossary Source missing from prompt")
      self.assertIn("<glossary_matches>", system_content, "XML tags missing from prompt")
      print("✅ CHECK PASSED: Glossary term and XML tags found in system prompt.")

    except AssertionError as e:
      print(f"❌ FAILED: RAG context missing. Details: {e}")
      raise e

  # FIX: Added 'app.chroma_client' patch here so we don't hit real DB logic
  @patch('app.chroma_client')
  @patch('app.upstream_client')
  def test_dry_run_safety(self, mock_openai, mock_chroma):
    """
    Test Safety Mechanism: The 'Dry Run' Model ID should NEVER hit the real API.
    """
    print("\n----------------------------------------------------------------------")
    print("🧪 TEST: Dry Run Safety")

    payload = {
      "model": "claude-opus-4-5-20251101",
      "messages": [{"role": "user", "content": "Secret dry run request"}]
    }

    response = self.app.post('/v1/chat/completions',
                             data=json.dumps(payload),
                             content_type='application/json')

    mock_openai.chat.completions.create.assert_not_called()
    print("🛡️  SAFETY CHECK PASSED: API Client was NOT called for dry run.")

    data = json.loads(response.data)
    self.assertEqual(data.get('id'), 'dry-run')
    print("✅ CHECK PASSED: Response ID indicated 'dry-run'.")

  def test_ping_health_check(self):
    """Test basic connectivity (Ping) to ensure the Flask app is running."""
    print("\n----------------------------------------------------------------------")
    print("🧪 TEST: Health Check (Ping)")

    payload = {
      "model": "deepseek-r1-v1",
      "messages": []
    }

    response = self.app.post('/v1/chat/completions',
                             data=json.dumps(payload),
                             content_type='application/json')

    self.assertEqual(response.status_code, 200)
    data = json.loads(response.data)
    self.assertEqual(data['choices'][0]['message']['content'], "Ping")
    print("✅ CHECK PASSED: Server returned 200 and 'Ping'.")

if __name__ == '__main__':
  unittest.main()
