"""
Unit Tests for Post-Processing Script
-------------------------------------
This suite tests the regex logic in `services/toolbox/src/post_process.py`.

Purpose:
  Drupal coding standards require variables (starting with %, @, !) to be 
  separated from Japanese text by half-width spaces.
  
  Example: "こんにちは%userさん" -> "こんにちは %user さん"

Tests cover:
  - Basic insertion of spaces.
  - Edge cases (start/end of string).
  - Multiple variables in one line.
  - Idempotency (ensuring we don't add double spaces if they already exist).

Run Command:
    docker compose run --rm toolbox python -m pytest /app/tests/unit/test_post_process.py
"""

import importlib.util
import unittest
import os
import sys
from unittest.mock import patch, MagicMock
from plugins.default import spacing_around_drupal_variables
from plugins.default import jp_en_spacing
import post_process # Core script

# sys.path hacking removed per refactoring - rely on PYTHONPATH


class TestDrupalVariablesPlugin(unittest.TestCase):

    def test_variable_spacing_basic(self):
        """Test standard case: Japanese char touching a variable."""
        input_text = 'msgstr "こんにちは%userさん"'
        expected = 'msgstr "こんにちは %user さん"'
        self.assertEqual(spacing_around_drupal_variables.run(input_text), expected)

    def test_variable_at_start_and_end(self):
        """Test when variable is at the very beginning or end of the string."""
        input_text = 'msgstr "%siteの構成"'
        expected = 'msgstr "%site の構成"'
        self.assertEqual(spacing_around_drupal_variables.run(input_text), expected)

    def test_multiple_variables(self):
        """Test strings containing multiple different variables."""
        input_text = 'msgstr "%fileは@sizeです"'
        expected = 'msgstr "%file は @size です"'
        self.assertEqual(spacing_around_drupal_variables.run(input_text), expected)

    def test_ignore_already_spaced(self):
        """Ensure the regex is safe to run on already-correct text (no double spaces)."""
        input_text = 'msgstr "こんにちは %user さん"'
        expected = 'msgstr "こんにちは %user さん"'
        self.assertEqual(spacing_around_drupal_variables.run(input_text), expected)

    def test_only_variable(self):
        """Test a string that is purely just a variable (no spaces needed)."""
        input_text = 'msgstr "%label"'
        expected = 'msgstr "%label"'
        self.assertEqual(spacing_around_drupal_variables.run(input_text), expected)
        
        
class TestCorePostProcess(unittest.TestCase):
    
    def test_disabled_via_env(self):
        """Test that the script exits early if the optional flag is disabled."""
        with patch.dict(os.environ, {"POST_PROCESSING_ENABLED": "false"}):
            with patch('post_process.sys.exit', side_effect=SystemExit) as mock_exit:
                # assertLogs captures records emitted by the 'post_process' logger
                with self.assertLogs('post_process', level='INFO') as log_cm:
                    with self.assertRaises(SystemExit):
                        post_process.main()

                # Should call sys.exit(0)
                mock_exit.assert_called_with(0)
                # Verify the expected log message was emitted
                self.assertTrue(
                    any('Post-processing is disabled' in line for line in log_cm.output),
                    f"Expected 'Post-processing is disabled' in log output.\nActual: {log_cm.output}"
                )

    @patch('post_process.check_plugin_conflicts')
    @patch('post_process.load_plugin')
    @patch('post_process.process_single_file')
    def test_plugin_loading(self, mock_process, mock_load, mock_conflicts):
        """Test that plugins are loaded based on language-specific env var."""
        with patch.dict(os.environ, {
            "POST_PROCESSING_ENABLED": "true",
            "POST_PROCESS_PLUGINS_JA": "test_plugin",
            "POST_PROCESS_INPUT_DIR": "/tmp" # Just in case
        }):
            # Mock sys.argv to avoid path error or exit
            with patch.object(sys, 'argv', ["script", "dummy_file.po", "--lang", "ja"]):
                # Mock file existence check
                with patch("os.path.isfile", return_value=True):
                    # Mock loading success
                    mock_plugin = MagicMock()
                    mock_load.return_value = mock_plugin
                    
                    # We expect process_single_file to be called
                    # mocking process_single_file avoids actual file I/O
                    
                    post_process.main()
                    
                    # Check load_plugin called with "test_plugin"
                    mock_load.assert_called_with("test_plugin")
                    
                    # Check process_single_file called with list containing mock_plugin
                    args, _ = mock_process.call_args
                    # args[0] is file, args[1] is loaded_plugins list
                    self.assertEqual(args[1], [mock_plugin])

    @patch('post_process.check_plugin_conflicts')
    @patch('post_process.load_plugin')
    @patch('post_process.process_single_file')
    @patch('post_process.find_po_files')
    @patch('os.path.isdir')
    @patch('os.path.isfile')
    def test_flat_discovery(self, mock_isfile, mock_isdir, mock_find_po, mock_process, mock_load, mock_conflicts):
        """Test that the script finds .po files at top level of directory."""
        # Setup mocks: /tmp is a dir, /tmp/file1.po is a file
        mock_isdir.side_effect = lambda p: p == "/tmp"
        mock_isfile.side_effect = lambda p: p in ["/tmp/file1.po", "/tmp/file2.po"]
        
        mock_find_po.return_value = ['/tmp/file1.po', '/tmp/file2.po']
        mock_load.return_value = MagicMock()

        with patch.dict(os.environ, {
            "POST_PROCESSING_ENABLED": "true",
            "POST_PROCESS_PLUGINS_JA": "test_plugin",
            "POST_PROCESS_INPUT_DIR": "/tmp"
        }):
            with patch.object(sys, 'argv', ["script", "/tmp", "--lang", "ja"]):
                post_process.main()
                
                # Verify shared utility was called to replace glob
                mock_find_po.assert_called_once_with("/tmp", recursive=False)
                
                # Verify both files were processed
                self.assertEqual(mock_process.call_count, 2)


class TestWaouSpacingPlugin(unittest.TestCase):
    """Tests for the Japanese-Alphanumeric (Waou) spacing logic."""

    def test_basic_insertion(self):
        """Test basic insertion between Kanji/Kana and Alphanumeric."""
        # Kanji + English
        self.assertEqual(jp_en_spacing.run('msgstr "漢字Text"'), 'msgstr "漢字 Text"')
        # English + Kanji
        self.assertEqual(jp_en_spacing.run('msgstr "Text漢字"'), 'msgstr "Text 漢字"')
        # Kana + Number
        self.assertEqual(jp_en_spacing.run('msgstr "テスト123"'), 'msgstr "テスト 123"')
        # Number + Kana
        self.assertEqual(jp_en_spacing.run('msgstr "123テスト"'), 'msgstr "123 テスト"')

    def test_idempotency(self):
        """Ensure we don't double space if space exists."""
        self.assertEqual(jp_en_spacing.run('msgstr "漢字 Text"'), 'msgstr "漢字 Text"')
        self.assertEqual(jp_en_spacing.run('msgstr "Text 漢字"'), 'msgstr "Text 漢字"')

    def test_exception_punctuation(self):
        """No space between Punctuation (。,、) and Alphanum."""
        self.assertEqual(jp_en_spacing.run('msgstr "文末。End"'), 'msgstr "文末。End"')
        self.assertEqual(jp_en_spacing.run('msgstr "項目、Item"'), 'msgstr "項目、Item"')

    def test_exception_units(self):
        """No space between Number and Degree symbol."""
        self.assertEqual(jp_en_spacing.run('msgstr "90°"'), 'msgstr "90°"')
        
    def test_exception_enclosures(self):
        """No space inside specific brackets/quotes."""
        # Parentheses
        self.assertEqual(jp_en_spacing.run('msgstr "関数(Func)"'), 'msgstr "関数(Func)"')
        self.assertEqual(jp_en_spacing.run('msgstr "(Func)関数"'), 'msgstr "(Func)関数"')
        # Brackets
        self.assertEqual(jp_en_spacing.run('msgstr "鍵[Key]"'), 'msgstr "鍵[Key]"')
        # Quotes
        self.assertEqual(jp_en_spacing.run('msgstr "引用\'Quote\'"'), 'msgstr "引用\'Quote\'"')
        self.assertEqual(jp_en_spacing.run('msgstr "引用\"Quote\""'), 'msgstr "引用\"Quote\""')
        # Japanese Brackets
        self.assertEqual(jp_en_spacing.run('msgstr "「Text」"'), 'msgstr "「Text」"')
        self.assertEqual(jp_en_spacing.run('msgstr "『Text』"'), 'msgstr "『Text』"')

    def test_exception_slashes(self):
        """No space around slashes."""
        self.assertEqual(jp_en_spacing.run('msgstr "日/Eng"'), 'msgstr "日/Eng"')
        self.assertEqual(jp_en_spacing.run('msgstr "Eng/日"'), 'msgstr "Eng/日"')

    def test_exception_terminators(self):
        """No space between Full-width and terminators like ? ! : ..."""
        self.assertEqual(jp_en_spacing.run('msgstr "本当?"'), 'msgstr "本当?"')
        self.assertEqual(jp_en_spacing.run('msgstr "驚き!"'), 'msgstr "驚き!"')
        self.assertEqual(jp_en_spacing.run('msgstr "例:Example"'), 'msgstr "例:Example"') 
        self.assertEqual(jp_en_spacing.run('msgstr "続く..."'), 'msgstr "続く..."')

    def test_exception_access_keys(self):
        """No space for Access Key pattern (S)."""
        self.assertEqual(jp_en_spacing.run('msgstr "保存(S)"'), 'msgstr "保存(S)"')
        self.assertEqual(jp_en_spacing.run('msgstr "開く(O)"'), 'msgstr "開く(O)"')


if __name__ == '__main__':
    unittest.main()
