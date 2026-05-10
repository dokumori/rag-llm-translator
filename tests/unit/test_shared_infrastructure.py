
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
        infrastructure._embedding_fn = None

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
        with patch.object(Config, "EMBEDDING_MODEL_NAME", "BAAI/bge-base-en-v1.5"):
            with patch.dict("os.environ", {"HF_HOME": "/fake/cache"}):
                with patch("os.path.isdir", return_value=True), \
                     patch("os.listdir", return_value=["models--BAAI--bge-base-en-v1.5"]):
                    infrastructure.get_embedding_function()

        mock_ef.assert_called_with(model_name="BAAI/bge-base-en-v1.5")

    def test_blocked_model_intfloat_e5_raises(self):
        """Models in the intfloat/e5-* family must be rejected."""
        with patch.object(Config, "EMBEDDING_MODEL_NAME", "intfloat/e5-large-v2"):
            with self.assertRaises(ValueError) as ctx:
                infrastructure.get_embedding_function()
        self.assertIn("query/passage prefixes", str(ctx.exception))

    def test_blocked_model_multilingual_e5_raises(self):
        """Models in the intfloat/multilingual-e5-* family must be rejected."""
        with patch.object(Config, "EMBEDDING_MODEL_NAME", "intfloat/multilingual-e5-large"):
            with self.assertRaises(ValueError) as ctx:
                infrastructure.get_embedding_function()
        self.assertIn("query/passage prefixes", str(ctx.exception))

    def test_supported_model_bge_is_not_blocked(self):
        """BAAI/bge-* models must pass the blocklist check."""
        with patch.object(Config, "EMBEDDING_MODEL_NAME", "BAAI/bge-base-en-v1.5"):
            with patch.dict("os.environ", {"HF_HOME": "/fake/cache"}):
                with patch("os.path.isdir", return_value=True), \
                     patch("os.listdir", return_value=["models--BAAI--bge-base-en-v1.5"]), \
                     patch("chromadb.utils.embedding_functions.SentenceTransformerEmbeddingFunction"):
                    # Should not raise
                    infrastructure.get_embedding_function()

    def test_empty_model_cache_raises(self):
        """Empty HF cache directory (no models-- dirs in hub/) must raise RuntimeError."""
        with patch.object(Config, "EMBEDDING_MODEL_NAME", "BAAI/bge-large-en-v1.5"):
            with patch.dict("os.environ", {"HF_HOME": "/fake/empty/cache"}):
                with patch("os.path.isdir", return_value=True), \
                     patch("os.listdir", return_value=["CACHEDIR.TAG", ".locks"]):  # no models--* dirs
                    with self.assertRaises(RuntimeError) as ctx:
                        infrastructure.get_embedding_function()
        self.assertIn("download-model.sh", str(ctx.exception))

    def test_missing_model_cache_dir_raises(self):
        """Missing hub/ directory must raise RuntimeError."""
        with patch.object(Config, "EMBEDDING_MODEL_NAME", "BAAI/bge-large-en-v1.5"):
            with patch.dict("os.environ", {"HF_HOME": "/nonexistent/path"}):
                with patch("os.path.isdir", return_value=False):
                    with self.assertRaises(RuntimeError) as ctx:
                        infrastructure.get_embedding_function()
        self.assertIn("download-model.sh", str(ctx.exception))
