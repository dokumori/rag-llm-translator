import re

def run(text):
    """
    Plugin: Spacing Around Drupal Variables
    Ensures variables like %variable, @variable, !variable are separated from Japanese text.
    """
    def process_msgstr(match):
        msgstr_content = match.group(1)

        # Define Drupal variable pattern: starts with %, !, or @ followed by ASCII alphanumerics
        # We use [a-zA-Z0-9_] instead of \w to avoid matching Japanese characters

        # 1. Multibyte char followed by Variable
        # Example: "こんにちは%user" -> "こんにちは %user"
        msgstr_content = re.sub(
            r'([^\x00-\x7F])([%!@][a-zA-Z0-9_]+)', r'\1 \2', msgstr_content)

        # 2. Variable followed by Multibyte char
        # Example: "%userさん" -> "%user さん"
        msgstr_content = re.sub(
            r'([%!@][a-zA-Z0-9_]+)([^\x00-\x7F])', r'\1 \2', msgstr_content)

        return f'msgstr "{msgstr_content}"'

    return re.sub(r'msgstr "([^"]*)"', process_msgstr, text)
