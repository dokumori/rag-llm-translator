import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Ensure we can import evaluate_blind_test (for local non-docker runs)
local_src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "services", "toolbox", "src"))
if os.path.exists(local_src_path):
    sys.path.append(local_src_path)

from evaluate_blind_test import load_po_translations, pair_translations, evaluate_translation, calculate_metrics, run_evaluation_loop

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
        entry1.msgctxt = None
        
        entry2 = MagicMock()
        entry2.msgid = "World"
        entry2.msgstr = "Monde"
        entry2.msgctxt = None
        
        # Ignored due to empty msgstr
        entry3 = MagicMock()
        entry3.msgid = "Empty"
        entry3.msgstr = ""
        entry3.msgctxt = None
        
        mock_po.__iter__.return_value = [entry1, entry2, entry3]
        mock_pofile.return_value = mock_po
        
        # Execute
        translations, found_files = load_po_translations("dummy/path")
        
        # Assertions
        self.assertEqual(len(translations), 2)
        # Now uses (msgid, msgctxt) tuples as keys
        self.assertEqual(translations[("Hello", "")], "Bonjour")
        self.assertEqual(translations[("World", "")], "Monde")
        self.assertNotIn(("Empty", ""), translations)
        self.assertEqual(found_files, ["dummy/path/file.po"])

    @patch("evaluate_blind_test.load_po_translations")
    def test_pair_translations(self, mock_load_po):
        """Test pairing of translations matching keys from both RAG and without RAG files."""
        # Setup mocks
        mock_load_po.side_effect = [
            # mock return for with_rag_dir: (translations_dict, files_list)
            ({("Key1", ""): "Val1_RAG", ("Key2", "ctx2"): "Val2_RAG"}, ["rag.po"]),
            # mock return for without_rag_dir: (translations_dict, files_list)
            ({("Key2", "ctx2"): "Val2_NO_RAG", ("Key3", ""): "Val3_NO_RAG"}, ["no_rag.po"])
        ]
        
        # Execute
        paired_data, with_rag_files, without_rag_files = pair_translations("rag_dir", "no_rag_dir")
        
        # Assertions
        # Only Key2 overlaps
        self.assertEqual(len(paired_data), 1)
        self.assertEqual(paired_data[0]["source"], "Key2")
        self.assertEqual(paired_data[0]["context"], "ctx2")
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
        sample = {
            "source": "Hello World",
            "context": "",
            "with_rag": "Bonjour le monde",
            "without_rag": "Salut monde"
        }
        
        # Format a full prompt with the new {source_context} placeholder
        prompt_template = "Source: {source_text}\n{source_context}RAG: {rag_context}\nA: {translation_a}\nB: {translation_b}"
        result = evaluate_translation(mock_client_instance, "fake-model", sample, prompt_template)
        
        # Assertions
        mock_choice.assert_called_once_with([True, False])
        self.assertIsNotNone(result)
        # Verify the RAG lookup was called with the new dictionary format
        mock_rag_lookup.assert_called_once_with([{"text": "Hello World", "context": ""}])
        
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
            '{"Better_Translation": "A", "Score_A": {"Context_Adherence": 4, "Accuracy_Fluency": 4, "Reason": "Good Non-RAG"}, "Score_B": {"Context_Adherence": 2, "Accuracy_Fluency": 2, "Reason": "Poor"}}\n'
            '```'
        )
        mock_client_instance.chat.completions.create.return_value = mock_response

        sample = {
            "source": "Hello World",
            "context": "",
            "with_rag": "Bonjour le monde",
            "without_rag": "Salut monde"
        }

        result = evaluate_translation(mock_client_instance, "fake-model", sample, "PROMPT {source_text} {source_context} {rag_context} {translation_a} {translation_b}")

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
            "context": "",
            "with_rag": "Test 1",
            "without_rag": "Test 2"
        }
        
        # Execute — pass a dummy MagicMock client; it won't be reached since RAG context is empty
        result = evaluate_translation(MagicMock(), "fake-model", sample, "PROMPT")
        
        # Assertion
        self.assertIsNone(result)

    def test_calculate_metrics_balanced(self):
        """Test math for a 50/50 split."""
        results = [
            {"winner": "with_rag", "with_rag_context": 5, "without_rag_context": 4, "with_rag_fluency": 5, "without_rag_fluency": 4},
            {"winner": "without_rag", "with_rag_context": 3, "without_rag_context": 5, "with_rag_fluency": 3, "without_rag_fluency": 5},
            {"winner": "tie", "with_rag_context": 4, "without_rag_context": 4, "with_rag_fluency": 4, "without_rag_fluency": 4}
        ]
        metrics = calculate_metrics(results)
        self.assertEqual(metrics["wins_with_rag"], 1)
        self.assertEqual(metrics["wins_without_rag"], 1)
        self.assertEqual(metrics["ties"], 1)
        self.assertEqual(metrics["win_ratio"], 1.0)
        self.assertEqual(metrics["net_win_rate"], 0.0)
        self.assertEqual(metrics["win_lead"], 0.0)

    def test_calculate_metrics_rag_dominance(self):
        """Test handling of 100% RAG wins."""
        results = [
            {"winner": "with_rag", "with_rag_context": 5, "without_rag_context": 2, "with_rag_fluency": 5, "without_rag_fluency": 2},
            {"winner": "with_rag", "with_rag_context": 4, "without_rag_context": 3, "with_rag_fluency": 4, "without_rag_fluency": 3}
        ]
        metrics = calculate_metrics(results)
        self.assertEqual(metrics["wins_with_rag"], 2)
        self.assertEqual(metrics["wins_without_rag"], 0)
        self.assertEqual(metrics["win_ratio"], float('inf'))
        self.assertEqual(metrics["relative_win_rate"], 100.0)
        self.assertEqual(metrics["net_win_rate"], 100.0)
        self.assertEqual(metrics["win_lead"], 100.0)

    def test_calculate_metrics_score_improvements(self):
        """Verify Contextual Error Reduction and Sub-optimal Rate Reduction logic."""
        results = [
            {"winner": "with_rag", "with_rag_context": 4.0, "without_rag_context": 3.0, "with_rag_fluency": 4.0, "without_rag_fluency": 3.0}
        ]
        metrics = calculate_metrics(results)
        
        # gap_without = 5.0 - 3.0 = 2.0
        # gap_with = 5.0 - 4.0 = 1.0
        # contextual_error_reduction = (2.0 - 1.0) / 2.0 * 100 = 50.0%
        self.assertEqual(metrics["contextual_error_reduction"], 50.0)
        
        # suboptimal_without = 1 (since 3.0 < 4.0)
        # suboptimal_with = 0 (since 4.0 >= 4.0)
        # suboptimal_reduction = (1 - 0) / 1 * 100 = 100.0%
        self.assertEqual(metrics["suboptimal_reduction"], 100.0)

    @patch("evaluate_blind_test.evaluate_translation")
    @patch("evaluate_blind_test.logger.info")
    def test_run_evaluation_loop_limit(self, mock_logger, mock_evaluate):
        """Verify the loop respects the --limit argument."""
        # Setup mock to return a generic result dict
        mock_evaluate.return_value = {"winner": "with_rag"}
        
        # We have 5 samples, but limit is 2
        paired_data = [{"source": f"txt{i}", "context": "", "with_rag": f"A{i}", "without_rag": f"B{i}"} for i in range(5)]
        client = MagicMock()
        
        results = run_evaluation_loop(client, "fake-model", paired_data, 2, "PROMPT {source_context}", False)
        
        self.assertEqual(len(results), 2)
        self.assertEqual(mock_evaluate.call_count, 2)

    @patch("evaluate_blind_test.evaluate_translation")
    def test_run_evaluation_loop_skipping(self, mock_evaluate):
        """Verify the loop skips failed evaluations correctly."""
        mock_evaluate.side_effect = [None, {"winner": "with_rag"}]
        
        paired_data = [{"source": "txt1", "context": "", "with_rag": "A1", "without_rag": "B1"}, {"source": "txt2", "context": "", "with_rag": "A2", "without_rag": "B2"}]
        client = MagicMock()
        
        results = run_evaluation_loop(client, "fake-model", paired_data, 0, "PROMPT", False)
        
        # Loop should run for all 2 items, but only 1 result is captured
        self.assertEqual(len(results), 1)
        self.assertEqual(mock_evaluate.call_count, 2)

if __name__ == "__main__":
    unittest.main()
