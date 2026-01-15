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

import unittest
import sys
import os

# FIXED PATH: Point to services/toolbox/src to find the script
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../services/toolbox/src')))
from post_process import add_spaces_to_variables

class TestPostProcess(unittest.TestCase):

  def test_variable_spacing_basic(self):
    """Test standard case: Japanese char touching a variable."""
    input_text = 'msgstr "こんにちは%userさん"'
    expected = 'msgstr "こんにちは %user さん"'
    self.assertEqual(add_spaces_to_variables(input_text), expected)

  def test_variable_at_start_and_end(self):
    """Test when variable is at the very beginning or end of the string."""
    input_text = 'msgstr "%siteの構成"'
    expected = 'msgstr "%site の構成"'
    self.assertEqual(add_spaces_to_variables(input_text), expected)

  def test_multiple_variables(self):
    """Test strings containing multiple different variables."""
    input_text = 'msgstr "%fileは@sizeです"'
    expected = 'msgstr "%file は @size です"'
    self.assertEqual(add_spaces_to_variables(input_text), expected)

  def test_ignore_already_spaced(self):
    """Ensure the regex is safe to run on already-correct text (no double spaces)."""
    input_text = 'msgstr "こんにちは %user さん"'
    expected = 'msgstr "こんにちは %user さん"'
    self.assertEqual(add_spaces_to_variables(input_text), expected)

  def test_only_variable(self):
    """Test a string that is purely just a variable (no spaces needed)."""
    input_text = 'msgstr "%label"'
    expected = 'msgstr "%label"'
    self.assertEqual(add_spaces_to_variables(input_text), expected)

if __name__ == '__main__':
  unittest.main()
