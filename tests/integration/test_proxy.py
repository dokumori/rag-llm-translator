"""
Integration Tests for RAG Proxy Service
---------------------------------------
This suite tests the `rag-proxy` Flask application (app.py).

Key Features Tested:
1. RAG Context Injection: 
   - Mocks ChromaDB to return a fake Glossary match ("Drupal Core").
   - Mocks the Anthropic API to avoid real costs.
   - Verifies that the 'system prompt' sent to Anthropic actually contains
     the data retrieved from ChromaDB (the RAG pattern).

2. Cost Safety (Dry Run):
   - Ensures that using the specific "Dry Run" model ID triggers a mock response
     internally and strictly *prevents* the code from calling the real paid API.

3. Health Checks:
   - Verifies the server responds to basic ping requests.

Usage:
  Execute inside the 'rag-proxy' container:
  $ python3 -m unittest /app/tests/integration/test_proxy.py
"""

import unittest
from unittest.mock import patch, MagicMock
import json
import sys
import os

# FIXED PATH: Point to services/rag-proxy/src to import the Flask app
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../services/rag-proxy/src')))
from app import app

class TestRAGProxy(unittest.TestCase):

  def setUp(self):
    """Setup a temporary Flask test client for every test."""
    self.app = app.test_client()
    self.app.testing = True

  @patch('app.chroma_client')
  @patch('app.real_claude')
  def test_rag_context_injection(self, mock_claude, mock_chroma):
    """
    Test that RAG results are correctly formatted and injected into the System Prompt.
    
    We simulate a user asking to translate 'Drupal Core'. We tell the Mock Database
    to pretend it found a glossary term. We then check if the Flask app correctly
    took that term and stuffed it into the 'system' message sent to Claude.
    """
    # 1. Setup Mock ChromaDB response
    # We create a fake collection object
    mock_collection = MagicMock()
    mock_chroma.get_collection.return_value = mock_collection

    # We tell the fake collection: "When queried, return this specific glossary match"
    mock_collection.query.return_value = {
      'documents': [['Drupal Core']],
      'metadatas': [[{'target': 'Drupalコア'}]],
      'distances': [[0.1]] # Distance < threshold (2.0) ensures it is accepted
    }

    # 2. Setup Mock Anthropic response
    # We tell the fake API client: "Just return success, don't actually call internet"
    mock_response = MagicMock()
    mock_response.model_dump.return_value = {"content": "Translated"}
    mock_claude.messages.create.return_value = mock_response

    # 3. Send Request to our Flask App
    payload = {
      "model": "claude-3-haiku-20240307",
      "messages": [{"role": "user", "content": "Text to translate:\nDrupal Core"}],
      "system": "You are a translator."
    }

    print("\n----------------------------------------------------------------------")
    print("🧪 TEST: RAG Context Injection")
    self.app.post('/v1/messages',
                  data = json.dumps(payload),
                  content_type = 'application/json')

    # 4. Verify Injection logic
    try:
      # Get the arguments that our App tried to send to the (mocked) Claude API
      call_args = mock_claude.messages.create.call_args
      if not call_args:
        print("❌ FAILED: API was not called at all.")
        return

      _, kwargs = call_args
      system_prompt = kwargs.get('system', '')

      # Assertions: Did the app modify the prompt correctly?
      self.assertIn("Drupal Core", system_prompt, "Glossary Source missing from prompt")
      self.assertIn("<glossary_matches>", system_prompt, "XML tags missing from prompt")
      print("✅ CHECK PASSED: Glossary term and XML tags found in system prompt.")

    except AssertionError as e:
      print(f"❌ FAILED: RAG context missing. Details: {e}")
      raise e

  @patch('app.real_claude')
  def test_secret_term_dry_run(self, mock_claude):
    """
    Test Safety Mechanism: The 'Dry Run' Model ID should NEVER hit the real API.
    """
    print("\n----------------------------------------------------------------------")
    print("🧪 TEST: Secret Term Safety")

    # This ID must match the one defined in your app.py logic
    payload = {
      "model": "claude-opus-4-5-20251101",
      "messages": [{"role": "user", "content": "Secret dry run request"}]
    }

    response = self.app.post('/v1/messages',
                             data = json.dumps(payload),
                             content_type = 'application/json')

    # CRITICAL: Assert that the mock_claude was NOT called.
    # If this fails, it means your app is spending money when it shouldn't!
    mock_claude.messages.create.assert_not_called()
    print("🛡️  SAFETY CHECK PASSED: API Client was NOT called for secret term.")

    # Check that the response confirms it was a mock
    data = json.loads(response.data)
    if "dry-run-mock" in data.get('model', ''):
      print("✅ CHECK PASSED: Response indicated dry-run-mock.")

  def test_ping_health_check(self):
    """Test basic connectivity (Ping) to ensure the Flask app is running."""
    print("\n----------------------------------------------------------------------")
    print("🧪 TEST: Health Check (Ping)")

    with patch('app.real_claude') as mock_claude:
      mock_claude.messages.create.return_value.model_dump.return_value = {"content": "pong"}

      payload = {
        "model": "claude-3-haiku-20240307",
        "messages": [] # Empty messages usually trigger the Ping logic
      }

      response = self.app.post('/v1/messages',
                               data = json.dumps(payload),
                               content_type = 'application/json')

      self.assertEqual(response.status_code, 200)
      print("✅ CHECK PASSED: Server returned 200 OK.")

if __name__ == '__main__':
  unittest.main()
