import os
import sys
import polib
from openai import OpenAI

def get_llm_client():
  try:
    # Connects to http://rag-proxy:5000/v1 based on env vars
    client = OpenAI()
    return client
  except Exception as e:
    print(f"❌ API Client Error: {e}", flush=True)
    sys.exit(1)

def translate_text(client, model, text):
  # We send raw text. The Proxy (app.py) handles the System Prompt and Instructions.
  messages = [{"role": "user", "content": text}]
  
  try:
    response = client.chat.completions.create(
      model = model,
      messages = messages,
      temperature = 0,
    )
    return response.choices[0].message.content.strip()
  except Exception as e:
    print(f"⚠️ API Error: {e}", flush=True)
    return text

def process_po_file(client, model, target_file):
  print(f"🔍 Processing: {target_file}", flush=True)
  
  try:
    po = polib.pofile(target_file)
    # Count total untranslated for progress tracking
    total_untranslated = len([e for e in po if not e.translated()])
    print(f"   Found {total_untranslated} items to translate.", flush=True)

    count = 0
    for entry in po:
      if not entry.translated():
        translation = translate_text(client, model, entry.msgid)
        
        if translation and translation.strip():
          entry.msgstr = translation
          count += 1
        
        # Log progress every 10 items
        if count % 10 == 0 and count > 0:
          print(f"   - Translated {count}/{total_untranslated}...", flush=True)

    # Save logic
    print(f"💾 Saving {count} translations to {target_file}...", flush=True)
    po.save(target_file)
    print(f"✅ Saved successfully.", flush=True)

  except Exception as e:
    print(f"❌ File Error: {e}", flush=True)

def main():
  if len(sys.argv) < 4:
    print("Usage: python3 translate_runner.py <model> <input_dir> <output_dir>")
    sys.exit(1)

  model_name = sys.argv[1]
  output_dir = sys.argv[3]

  print(f"🔌 Connecting to API using model: {model_name}")
  
  # Initialize Client
  client = get_llm_client()

  # Iterate over files in the output directory (which were copied by translate.sh)
  for filename in os.listdir(output_dir):
    if filename.endswith(".po"):
      target_path = os.path.join(output_dir, filename)
      process_po_file(client, model_name, target_path)

if __name__ == "__main__":
  main()
