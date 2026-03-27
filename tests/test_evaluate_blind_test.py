import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Ensure we can import evaluate_blind_test (for local non-docker runs)
local_src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "services", "toolbox", "src"))
if os.path.exists(local_src_path):
    sys.path.append(local_src_path)

from evaluate_blind_test import load_po_translations, pair_translations, evaluate_translation

class TestEvaluateBlindTest(unittest.TestCase):
    
    @patch("evaluate_blind_test.glob.glob")
    @patch("evaluate_blind_test.polib.pofile")
    def test_load_po_translations(self, mock_pofile, mock_glob):
        """Test that load_po_translations correctly parses valid PO files."""
        # Setup mocks
        mock_glob.return_value = ["dummy/path/file.po"]
        
        mock_po = MagicMock()
        
        # Create fake PO entries
        entry1 = MagicMock()
        entry1.msgid = "Hello"
        entry1.msgstr = "Bonjour"
        
        entry2 = MagicMock()
        entry2.msgid = "World"
        entry2.msgstr = "Monde"
        
        # Ignored due to empty msgstr
        entry3 = MagicMock()
        entry3.msgid = "Empty"
        entry3.msgstr = ""
        
        mock_po.__iter__.return_value = [entry1, entry2, entry3]
        mock_pofile.return_value = mock_po
        
        # Execute
        translations, found_files = load_po_translations("dummy/path")
        
        # Assertions
        self.assertEqual(len(translations), 2)
        self.assertEqual(translations["Hello"], "Bonjour")
        self.assertEqual(translations["World"], "Monde")
        self.assertNotIn("Empty", translations)
        self.assertEqual(found_files, ["dummy/path/file.po"])

    @patch("evaluate_blind_test.load_po_translations")
    def test_pair_translations(self, mock_load_po):
        """Test pairing of translations matching keys from both RAG and without RAG files."""
        # Setup mocks
        mock_load_po.side_effect = [
            # mock return for with_rag_dir: (translations_dict, files_list)
            ({"Key1": "Val1_RAG", "Key2": "Val2_RAG"}, ["rag.po"]),
            # mock return for without_rag_dir: (translations_dict, files_list)
            ({"Key2": "Val2_NO_RAG", "Key3": "Val3_NO_RAG"}, ["no_rag.po"])
        ]
        
        # Execute
        paired_data, with_rag_files, without_rag_files = pair_translations("rag_dir", "no_rag_dir")
        
        # Assertions
        # Only Key2 overlaps
        self.assertEqual(len(paired_data), 1)
        self.assertEqual(paired_data[0]["source"], "Key2")
        self.assertEqual(paired_data[0]["with_rag"], "Val2_RAG")
        self.assertEqual(paired_data[0]["without_rag"], "Val2_NO_RAG")
        self.assertEqual(with_rag_files, ["rag.po"])
        self.assertEqual(without_rag_files, ["no_rag.po"])

    @patch("evaluate_blind_test.perform_rag_lookup")
    @patch("evaluate_blind_test.random.choice")
    def test_evaluate_translation_with_rag_winner(self, mock_choice, mock_rag_lookup):
        """Test evaluation logic when the LLM successfully chooses A (which is mapped to with_rag)."""
        # Setup mocks
        mock_rag_lookup.return_value = ("<tm_matches>\nSource: Hello\nTarget: Bonjour\n</tm_matches>", [])
        mock_choice.return_value = True  # with_rag is injected as A, without_rag is injected as B
        
        # Mock OpenAI Client directly since it is now passed in as a parameter
        mock_client_instance = MagicMock()
        
        mock_response = MagicMock()
        # Simulate LLM choosing A (with_rag). Use a clean, single-line JSON string
        # to avoid any ambiguity with the markdown-stripping logic in evaluate_translation.
        mock_response.choices[0].message.content = (
            '```json\n'
            '{"Better_Translation": "A", "Score_A": {"Context_Adherence": 5, "Accuracy_Fluency": 4, "Reason": "Great"}, "Score_B": {"Context_Adherence": 3, "Accuracy_Fluency": 3, "Reason": "Okay"}}\n'
            '```'
        )
        mock_client_instance.chat.completions.create.return_value = mock_response
        
        sample = {
            "source": "Hello World",
            "with_rag": "Bonjour le monde",
            "without_rag": "Salut monde"
        }
        
        # Execute
        result = evaluate_translation(mock_client_instance, "fake-model", sample, "PROMPT TEMPLATE {source_text} {rag_context} {translation_a} {translation_b}")
        
        # Assertions
        mock_choice.assert_called_once_with([True, False])
        self.assertIsNotNone(result)
        self.assertEqual(result["winner"], "with_rag")
        self.assertEqual(result["with_rag_context"], 5)
        self.assertEqual(result["with_rag_fluency"], 4)
        self.assertEqual(result["without_rag_context"], 3)
        self.assertEqual(result["source"], "Hello World")
        self.assertEqual(result["with_rag_translation"], "Bonjour le monde")

    @patch("evaluate_blind_test.perform_rag_lookup")
    @patch("evaluate_blind_test.random.choice")
    def test_evaluate_translation_without_rag_winner(self, mock_choice, mock_rag_lookup):
        """
        Test evaluation logic when is_with_rag_a=False (without_rag is A, with_rag is B).
        When the LLM chooses A, the winner should correctly resolve to 'without_rag',
        and the scores should be mapped to the right translation groups in reverse.
        """
        mock_rag_lookup.return_value = ("<tm_matches>\nSource: Hello\nTarget: Bonjour\n</tm_matches>", [])
        mock_choice.return_value = False  # without_rag is injected as A, with_rag is injected as B

        # Mock OpenAI Client directly since it is now passed in as a parameter
        mock_client_instance = MagicMock()

        mock_response = MagicMock()
        # LLM chooses A — but A is without_rag this time, so winner must resolve to 'without_rag'.
        # Scores for A (without_rag) should be mapped to without_rag_*, and B (with_rag) to with_rag_*.
        mock_response.choices[0].message.content = (
            '```json\n'
            '{"Better_Translation": "A", "Score_A": {"Context_Adherence": 4, "Accuracy_Fluency": 4, "Reason": "Good baseline"}, "Score_B": {"Context_Adherence": 2, "Accuracy_Fluency": 2, "Reason": "Poor"}}\n'
            '```'
        )
        mock_client_instance.chat.completions.create.return_value = mock_response

        sample = {
            "source": "Hello World",
            "with_rag": "Bonjour le monde",
            "without_rag": "Salut monde"
        }

        result = evaluate_translation(mock_client_instance, "fake-model", sample, "PROMPT TEMPLATE {source_text} {rag_context} {translation_a} {translation_b}")

        mock_choice.assert_called_once_with([True, False])
        self.assertIsNotNone(result)
        # A was without_rag, and LLM picked A — so winner should be without_rag
        self.assertEqual(result["winner"], "without_rag")
        # Score_A belongs to without_rag (A), Score_B belongs to with_rag (B) 
        self.assertEqual(result["without_rag_context"], 4)
        self.assertEqual(result["without_rag_fluency"], 4)
        self.assertEqual(result["with_rag_context"], 2)
        self.assertEqual(result["with_rag_fluency"], 2)

    @patch("evaluate_blind_test.perform_rag_lookup")
    def test_evaluate_translation_skipped_no_context(self, mock_rag_lookup):
        """Test evaluation skipping when there is no valid RAG context."""
        # Mock empty RAG context
        mock_rag_lookup.return_value = ("", [])
        
        sample = {
            "source": "No Context Test",
            "with_rag": "Test 1",
            "without_rag": "Test 2"
        }
        
        # Execute — pass a dummy MagicMock client; it won't be reached since RAG context is empty
        result = evaluate_translation(MagicMock(), "fake-model", sample, "PROMPT")
        
        # Assertion
        self.assertIsNone(result)

if __name__ == "__main__":
    unittest.main()
