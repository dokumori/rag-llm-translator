
"""
Unit Test: Shared Infrastructure
------------------------------
Tests the shared database and embedding logic.
"""
import unittest
from unittest.mock import MagicMock, patch
from core.config import Config
import infrastructure

class TestSharedInfrastructure(unittest.TestCase):

    def setUp(self):
        # Reset singletons before each test
        infrastructure._chroma_client = None
        infrastructure._e5_ef = None

    @patch("chromadb.HttpClient")
    def test_get_chroma_client_singleton(self, mock_chroma):
        """Verify client is created once and cached."""
        # 1st call
        client1 = infrastructure.get_chroma_client()
        # 2nd call
        client2 = infrastructure.get_chroma_client()
        
        self.assertEqual(client1, client2)
        mock_chroma.assert_called_once()
    
    @patch("chromadb.utils.embedding_functions.SentenceTransformerEmbeddingFunction")
    def test_get_embedding_function(self, mock_ef):
        """Verify embedding function uses config model name."""
        infrastructure.get_embedding_function()
        
        mock_ef.assert_called_with(model_name=Config.EMBEDDING_MODEL_NAME)
