import unittest
import sys
import os

# Add scripts/ to path so we can import the module
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../scripts')))
from post_process import add_spaces_to_variables

class TestPostProcess(unittest.TestCase):

  def test_variable_spacing_basic(self):
    """Test that spaces are added between Japanese text and variables."""
    # Case 1: Japanese followed by Variable
    input_text = 'msgstr "こんにちは%userさん"'
    expected = 'msgstr "こんにちは %user さん"'
    self.assertEqual(add_spaces_to_variables(input_text), expected)

  def test_variable_at_start_and_end(self):
    """Test variables at start/end of string aren't broken."""
    input_text = 'msgstr "%siteの構成"'
    expected = 'msgstr "%site の構成"'
    self.assertEqual(add_spaces_to_variables(input_text), expected)

  def test_multiple_variables(self):
    """Test multiple variables in one string."""
    input_text = 'msgstr "%fileは@sizeです"'
    expected = 'msgstr "%file は @size です"'
    self.assertEqual(add_spaces_to_variables(input_text), expected)

  def test_ignore_already_spaced(self):
    """Ensure we don't double-space if spaces exist."""
    input_text = 'msgstr "こんにちは %user さん"'
    expected = 'msgstr "こんにちは %user さん"'
    self.assertEqual(add_spaces_to_variables(input_text), expected)

  def test_only_variable(self):
    """Test strings that are only a variable."""
    input_text = 'msgstr "%label"'
    expected = 'msgstr "%label"'
    self.assertEqual(add_spaces_to_variables(input_text), expected)

if __name__ == '__main__':
  unittest.main()
