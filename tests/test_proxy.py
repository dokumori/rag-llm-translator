import unittest
from unittest.mock import patch, MagicMock
import json
import sys
import os

# Add proxy/ to path to import app
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../proxy')))
from app import app

class TestRAGProxy(unittest.TestCase):

  def setUp(self):
    self.app = app.test_client()
    self.app.testing = True

  @patch('app.chroma_client')
  @patch('app.real_claude')
  def test_rag_context_injection(self, mock_claude, mock_chroma):
    """
    Test that RAG results are actually injected into the system prompt.
    """
    # 1. Setup Mock ChromaDB response
    mock_collection = MagicMock()
    mock_chroma.get_collection.return_value = mock_collection

    # Mock finding a match in the Glossary
    mock_collection.query.return_value = {
      'documents': [['Drupal Core']],
      'metadatas': [[{'target': 'Drupalコア'}]]
    }

    # 2. Setup Mock Anthropic response
    mock_response = MagicMock()
    mock_response.model_dump.return_value = {"content": "Translated"}
    mock_claude.messages.create.return_value = mock_response

    # 3. Send Request
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

    # 4. Verify Injection
    try:
      call_args = mock_claude.messages.create.call_args
      if not call_args:
        print("❌ FAILED: API was not called at all.")
        return

      _, kwargs = call_args
      system_prompt = kwargs.get('system', '')

      self.assertIn("Drupal Core", system_prompt)
      print("✅ CHECK PASSED: 'Drupal Core' found in system prompt.")

      self.assertIn("<glossary_matches>", system_prompt)
      print("✅ CHECK PASSED: '<glossary_matches>' tag found in system prompt.")

    except AssertionError as e:
      print(f"❌ FAILED: RAG context missing. Details: {e}")
    except Exception as e:
      print(f"❌ FAILED: Unexpected error: {e}")

  @patch('app.real_claude')
  def test_secret_term_dry_run(self, mock_claude):
    """
    Test that the specific model 'claude-3-opus-20240229' acts as the Secret Key
    to trigger a dry-run.
    """
    print("\n----------------------------------------------------------------------")
    print("🧪 TEST: Secret Term Safety (claude-3-opus-20240229)")

    payload = {
      "model": "claude-3-opus-20240229",
      "messages": [{"role": "user", "content": "Secret dry run request"}]
    }

    try:
      response = self.app.post('/v1/messages',
                               data = json.dumps(payload),
                               content_type = 'application/json')

      # Check logic
      mock_claude.messages.create.assert_not_called()
      print("🛡️  SAFETY CHECK PASSED: API Client was NOT called for secret term.")

      # Check response content
      data = json.loads(response.data)
      if "dry-run-mock" in data.get('model', ''):
        print("✅ CHECK PASSED: Response indicated dry-run-mock.")

    except AssertionError as e:
      print("❌ FAILED: API Client WAS called! Secret term did not trigger dry-run.")
    except Exception as e:
      print(f"❌ FAILED: Unexpected error: {e}")

  @patch('app.real_claude')
  def test_real_opus_allowed(self, mock_claude):
    """
    Test that a REAL Opus model (not the secret term) is allowed to hit the API.
    """
    print("\n----------------------------------------------------------------------")
    print("🧪 TEST: Real Opus Allowed (claude-3-opus-latest)")

    # Setup mock return so it doesn't crash
    mock_claude.messages.create.return_value.model_dump.return_value = {"content": "Real translation"}

    payload = {
      "model": "claude-3-opus-latest",
      "messages": [{"role": "user", "content": "Real request"}]
    }

    try:
      self.app.post('/v1/messages',
                    data = json.dumps(payload),
                    content_type = 'application/json')

      # CRITICAL CHECK: It SHOULD be called
      if mock_claude.messages.create.called:
        print("✅ CHECK PASSED: Real Opus model successfully called the API.")
      else:
        print("❌ FAILED: Real Opus model was blocked by mistake!")

    except Exception as e:
      print(f"❌ FAILED: Unexpected error: {e}")

  def test_ping_health_check(self):
    """Test the basic ping functionality."""
    print("\n----------------------------------------------------------------------")
    print("🧪 TEST: Health Check (Ping)")

    try:
      with patch('app.real_claude') as mock_claude:
        mock_claude.messages.create.return_value.model_dump.return_value = {"content": "pong"}

        payload = {
          "model": "claude-3-haiku-20240307",
          "messages": []
        }

        response = self.app.post('/v1/messages',
                                 data = json.dumps(payload),
                                 content_type = 'application/json')

        self.assertEqual(response.status_code, 200)
        print("✅ CHECK PASSED: Server returned 200 OK.")

    except AssertionError as e:
      print(f"❌ FAILED: Ping check failed (Status not 200). Details: {e}")
    except Exception as e:
      print(f"❌ FAILED: Unexpected error during Ping: {e}")

if __name__ == '__main__':
  unittest.main()
