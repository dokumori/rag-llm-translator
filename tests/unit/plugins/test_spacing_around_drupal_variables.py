import pytest
from plugins.default import spacing_around_drupal_variables

@pytest.mark.parametrize("input_text, expected", [
    ('msgstr "こんにちは%userさん"', 'msgstr "こんにちは %user さん"'),
    ('msgstr "%siteの構成"', 'msgstr "%site の構成"'),
    ('msgstr "%fileは@sizeです"', 'msgstr "%file は @size です"'),
    ('msgstr "こんにちは %user さん"', 'msgstr "こんにちは %user さん"'),
    ('msgstr "%label"', 'msgstr "%label"'),
])
def test_drupal_variable_spacing(input_text, expected):
    """Test various scenarios for Drupal variable spacing."""
    assert spacing_around_drupal_variables.run(input_text) == expected
