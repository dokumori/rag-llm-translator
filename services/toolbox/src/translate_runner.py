import os
import sys
import polib
from openai import OpenAI

def get_llm_client():
  """
  Initializes the OpenAI client for Amazee.ai.
  Relies on environment variables set in translate.sh:
  - OPENAI_API_KEY
  - OPENAI_BASE_URL
  """
  # Drupal Standard: 2-space indent
  # The OpenAI client automatically looks for OPENAI_API_KEY and OPENAI_BASE_URL
  # in the environment, so no arguments are needed here if env vars are set.
  try:
    client = OpenAI()
    return client
  except Exception as e:
    print(f"❌ Error initializing API client: {e}")
    sys.exit(1)

def translate_text(client, model, text, context = ""):
  """
  Sends the text to the LLM for translation.
  """
  # DRY RUN CHECK:
  # If the model is the specific dry-run ID, return a mock translation.
  if model == "claude-opus-4-5-20251101":
    return f"[DRY_RUN] {text}"

  # specific prompt for Drupal PO files
  system_prompt = (
    "You are a professional translator for Drupal CMS."
    "Translate the following text into the target language (assumed Japanese/Target based on context)."
    "Keep HTML tags and placeholders (like @variable or %variable) intact."
    "Do not add explanations, only return the translated string."
  )

  messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": f"Translate this: {text}"}
  ]

  try:
    # Amazee.ai / OpenAI Chat Completion Call
    response = client.chat.completions.create(
      model = model,
      messages = messages,
      temperature = 0,
    )
    
    # Extract the content from the response
    translated_text = response.choices[0].message.content.strip()
    return translated_text

  except Exception as e:
    print(f"⚠️ API Call failed for '{text[:20]}...': {e}")
    return text # Return original on failure to avoid breaking the file

def process_po_file(client, model, input_file, output_file):
  """
  Reads a PO file, translates untranslated entries, and saves it.
  """
  print(f"Processing: {input_file}")
  
  try:
    po = polib.pofile(input_file)
    
    count = 0
    total = len([e for e in po if not e.translated()])

    for entry in po:
      if not entry.translated():
        # Drupal Standard: space around =
        translation = translate_text(client, model, entry.msgid)
        entry.msgstr = translation
        count += 1
        
        # Simple progress indicator
        if count % 5 == 0:
          print(f"  - Translated {count}/{total} entries...")

    po.save(output_file)
    print(f"✅ Saved to: {output_file}")

  except Exception as e:
    print(f"❌ Failed to process {input_file}: {e}")

def main():
  # Arguments passed from translate.sh
  if len(sys.argv) < 4:
    print("Usage: python3 translate_runner.py <model> <input_dir> <output_dir>")
    sys.exit(1)

  model_name = sys.argv[1]
  input_dir = sys.argv[2]
  output_dir = sys.argv[3]

  print(f"🔌 Connecting to API using model: {model_name}")
  
  # Initialize Client
  client = get_llm_client()

  # Ensure output directory exists
  if not os.path.exists(output_dir):
    os.makedirs(output_dir)

  # Iterate over .po files in input directory
  for filename in os.listdir(input_dir):
    if filename.endswith(".po"):
      input_path = os.path.join(input_dir, filename)
      output_path = os.path.join(output_dir, filename)
      
      process_po_file(client, model_name, input_path, output_path)

if __name__ == "__main__":
  main()
