import re

def run(text):
    """
    Plugin: Japanese-English (Waou) Spacing
    Inserts a half-width space between Japanese (Full-width) and Alphanumeric (Half-width) characters.
    """
    def process_waou(match):
        content = match.group(1)
        
        # 1. Insert space between Full-width <-> Half-width boundaries
        # Use simple lookahead/lookbehind approach or substitution
        # [^\x00-\x7F] matches non-ASCII (assuming Japenese/Full-width)
        # [a-zA-Z0-9] matches alphanumeric
        
        # Boundary: Full-width followed by Half-width (Alphanum)
        # Ex: "漢字Text" -> "漢字 Text"
        # We ensure no space exists already by checking the boundary directly.
        content = re.sub(r'([^\x00-\x7F])([a-zA-Z0-9])', r'\1 \2', content)

        # Boundary: Half-width (Alphanum) followed by Full-width
        # Ex: "Text漢字" -> "Text 漢字"
        content = re.sub(r'([a-zA-Z0-9])([^\x00-\x7F])', r'\1 \2', content)

        # 2. Handle Exceptions (Remove the spaces we just added or generally shouldn't exist)
        
        # Exception: Punctuation (Ideographic period/comma) + Alphanum
        # "。" or "、" followed by space then Alphanum -> Remove space
        content = re.sub(r'([。、]) ([a-zA-Z0-9])', r'\1\2', content)

        # Exception: Units (Number + space + Degree symbol) -> Remove space
        # Note: Degree symbol often handled as non-ascii, so checking specifics
        content = re.sub(r'([0-9]) (°)', r'\1\2', content)

        # Exception: Enclosures
        # Remove space after opening or before closing brackets/quotes if adjacent to OTHER char type
        # Patterns: 
        #   Open + space + content -> Open + content
        #   Content + space + Close -> Content + Close
        # We target specific brackets: () [] {} "" '' 「」 『』
        # Note: We focus on where the spaces might have been added at the FW/HW boundary.
        
        # Case: "「" (FW) + space + "Half" (HW) -> Remove space
        content = re.sub(r'([「『]) ([a-zA-Z0-9])', r'\1\2', content)
        
        # Case: "Half" (HW) + space + "」" (FW) -> Remove space
        content = re.sub(r'([a-zA-Z0-9]) ([」』])', r'\1\2', content)

        # Case: "Full" (FW) + space + ")" (HW) -> Remove space
        content = re.sub(r'([^\x00-\x7F]) ([)\]}"\'])', r'\1\2', content)

        # Case: "(" (HW) + space + "Full" (FW) -> Remove space
        content = re.sub(r'([(\[{"\']) ([^\x00-\x7F])', r'\1\2', content)

        # Exception: Slashes
        # "Full" / "Half" or "Half" / "Full"
        content = re.sub(r' / ', '/', content)  # Simplistic cleanup around slashes if spaces added
        # More precise: Remove space if slash is involved in the boundary
        content = re.sub(r'([^\x00-\x7F]) (/)', r'\1\2', content)
        content = re.sub(r'(/) ([^\x00-\x7F])', r'\1\2', content)

        # Exception: Terminators (Full-width char + space + punctuation)
        # Ex: "漢字 ?" -> "漢字?"
        content = re.sub(r'([^\x00-\x7F]) ([?!:;])', r'\1\2', content)
        content = re.sub(r'([^\x00-\x7F]) (\.\.\.)', r'\1\2', content)

        # Exception: Access Keys "保存(S)" pattern
        # "Char" + space + "(S)" -> "Char(S)"
        # Regex: Any char, space, (, single letter, )
        content = re.sub(r' (.) \(([a-zA-Z0-9])\)', r'\1(\2)', content)

        return f'msgstr "{content}"'

    return re.sub(r'msgstr "([^"]*)"', process_waou, text)
