import pytest
from plugins.default import jp_en_spacing

@pytest.mark.parametrize("input_text, expected", [
    # Basic Insertion
    ('msgstr "漢字Text"', 'msgstr "漢字 Text"'),
    ('msgstr "Text漢字"', 'msgstr "Text 漢字"'),
    ('msgstr "テスト123"', 'msgstr "テスト 123"'),
    ('msgstr "123テスト"', 'msgstr "123 テスト"'),
    
    # Idempotency
    ('msgstr "漢字 Text"', 'msgstr "漢字 Text"'),
    ('msgstr "Text 漢字"', 'msgstr "Text 漢字"'),
    
    # Exceptions: Punctuation
    ('msgstr "文末。End"', 'msgstr "文末。End"'),
    ('msgstr "項目、Item"', 'msgstr "項目、Item"'),
    
    # Exceptions: Units
    ('msgstr "90°"', 'msgstr "90°"'),
    
    # Exceptions: Enclosures
    ('msgstr "関数(Func)"', 'msgstr "関数(Func)"'),
    ('msgstr "(Func)関数"', 'msgstr "(Func)関数"'),
    ('msgstr "鍵[Key]"', 'msgstr "鍵[Key]"'),
    ('msgstr "引用\'Quote\'"', 'msgstr "引用\'Quote\'"'),
    ('msgstr "引用\"Quote\""', 'msgstr "引用\"Quote\""'),
    ('msgstr "「Text」"', 'msgstr "「Text」"'),
    ('msgstr "『Text』"', 'msgstr "『Text』"'),
    
    # Exceptions: Slashes
    ('msgstr "日/Eng"', 'msgstr "日/Eng"'),
    ('msgstr "Eng/日"', 'msgstr "Eng/日"'),
    
    # Exceptions: Terminators
    ('msgstr "本当?"', 'msgstr "本当?"'),
    ('msgstr "驚き!"', 'msgstr "驚き!"'),
    ('msgstr "例:Example"', 'msgstr "例:Example"'),
    ('msgstr "続く..."', 'msgstr "続く..."'),
    
    # Exceptions: Access Keys
    ('msgstr "保存(S)"', 'msgstr "保存(S)"'),
    ('msgstr "開く(O)"', 'msgstr "開く(O)"'),
])
def test_jp_en_spacing(input_text, expected):
    """Test scenarios for Japanese-English (Waou) spacing."""
    assert jp_en_spacing.run(input_text) == expected
