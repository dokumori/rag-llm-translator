import os
import sys
import polib
import json
import glob
from openai import OpenAI

# Configuration
BATCH_SIZE = 15

def get_llm_client():
  try:
    client = OpenAI()
    return client
  except Exception as e:
    print(f"❌ API Client Error: {e}", flush=True)
    sys.exit(1)

def translate_batch(client, model, texts):
  """
  Sends a batch of texts to the RAG proxy as a JSON string.
  """
  content_str = json.dumps(texts, ensure_ascii=False)
  messages = [{"role": "user", "content": content_str}]
  
  try:
    response = client.chat.completions.create(
      model=model,
      messages=messages,
      temperature=0,
    )
    response_content = response.choices[0].message.content.strip()
    
    # Clean potential markdown wrapping
    if "```" in response_content:
      response_content = response_content.split("```json")[-1].split("```")[0].strip()
    
    translated_list = json.loads(response_content)
    
    if isinstance(translated_list, list) and len(translated_list) == len(texts):
      return translated_list
    return None

  except Exception as e:
    print(f"⚠️ Batch Error: {e}", flush=True)
    return None

def translate_single_fallback(client, model, text):
  """Fallback for failed batches"""
  try:
    messages = [{"role": "user", "content": text}]
    response = client.chat.completions.create(
      model=model,
      messages=messages,
      temperature=0,
    )
    return response.choices[0].message.content.strip()
  except Exception:
    return text

MAX_BATCH_SIZE = 15
MAX_CHARS_PER_BATCH = 4000 # Roughly 1000-1500 tokens

def process_po_file(client, model, input_file, output_file):
  print(f"🔍 Processing: {input_file}", flush = True)
  os.makedirs(os.path.dirname(output_file), exist_ok = True)
  
  try:
    po = polib.pofile(input_file)
    untranslated_entries = [e for e in po if not e.translated()]
    total = len(untranslated_entries)
    
    if total == 0:
      po.save(output_file)
      return

    print(f"   📝 Found {total} items. Starting smart batching...", flush = True)

    cursor = 0
    batch_count = 0
    
    while cursor < total:
      current_batch_entries = []
      current_batch_chars = 0
      
      # Build a batch dynamically
      while len(current_batch_entries) < MAX_BATCH_SIZE and cursor < total:
        entry = untranslated_entries[cursor]
        entry_len = len(entry.msgid)
        
        # If adding this entry exceeds our char limit, and we already have items, stop here.
        if (current_batch_chars + entry_len) > MAX_CHARS_PER_BATCH and len(current_batch_entries) > 0:
          break
          
        current_batch_entries.append(entry)
        current_batch_chars += entry_len
        cursor += 1

      # Translate the dynamic batch
      batch_texts = [e.msgid for e in current_batch_entries]
      batch_count += 1
      
      translated_texts = translate_batch(client, model, batch_texts)
      
      if translated_texts:
        for entry, translation in zip(current_batch_entries, translated_texts):
          if translation and translation.strip():
            entry.msgstr = translation
      else:
        # Fallback for the whole batch
        for entry in current_batch_entries:
          entry.msgstr = translate_single_fallback(client, model, entry.msgid)

      # Progress logging
      percent = (cursor / total) * 100
      print(f"   - Batch {batch_count} done. [{cursor}/{total}] ({percent:.1f}%)", flush = True)
      
      # Save every batch
      po.save(output_file)

    print(f"   💾 Saved to: {output_file}", flush = True)

  except Exception as e:
    print(f"❌ Failed: {e}", flush = True)

def main():
  if len(sys.argv) < 4:
    print("Usage: python3 translate_runner.py <model> <input_dir> <output_dir>")
    sys.exit(1)

  model_name = sys.argv[1]
  input_base_dir = sys.argv[2]
  output_base_dir = sys.argv[3]

  print(f"🔌 Connecting to API using model: {model_name}")

  client = get_llm_client()

  # RECURSIVE SEARCH
  po_files = glob.glob(os.path.join(input_base_dir, "**/*.po"), recursive=True)
  
  if not po_files:
    print(f"⚠️ No .po files found in {input_base_dir}", flush=True)
    return

  print(f"🚀 Found {len(po_files)} PO files to process.", flush=True)

  for src_file in po_files:
    # Calculate relative path to mirror structure in output
    rel_path = os.path.relpath(src_file, input_base_dir)
    final_dest_file = os.path.join(output_base_dir, rel_path)
    
    process_po_file(client, model_name, src_file, final_dest_file)

if __name__ == "__main__":
  main()
