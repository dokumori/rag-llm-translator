from flask import Flask, request, jsonify
import chromadb
import anthropic
import os
import sys
import json
import time

app = Flask(__name__)

# Clients
real_claude = anthropic.Anthropic(api_key = os.environ.get("ANTHROPIC_API_KEY"))
chroma_client = chromadb.HttpClient(
  host = os.environ.get("CHROMA_HOST", "chroma"),
  port = int(os.environ.get("CHROMA_PORT", 8000))
)

def get_system_prompt_from_md():
  path = "/app/system_prompt.md"
  if os.path.exists(path):
    with open(path, "r", encoding = "utf-8") as f:
      return f.read()
  return "You are a professional translator."

@app.route('/v1/messages', methods = ['POST'])
def handle_translation():
  try:
    data = request.json
    messages = data.get('messages', [])
    user_messages = [m for m in messages if m.get('role') == 'user']

    requested_model = data.get('model', "claude-3-haiku-20240307")

    # --- 1. VALIDATION / PING CHECK ---
    if not user_messages:
      return jsonify(real_claude.messages.create(
        model = "claude-3-haiku-20240307", 
        max_tokens = 10,
        messages = [{"role": "user", "content": "Ping"}]
      ).model_dump())

    source_text = user_messages[-1].get('content', '')
# --- 2. EXTRACT CONTENT FOR RAG ---
    # Parse the JSON list from the user prompt to isolate specific strings.
    query_payload = []

    try:
      list_start = source_text.rfind('[')
      if list_start != -1:
        json_part = source_text[list_start:]
        batch_items = json.loads(json_part)
        if isinstance(batch_items, list):
          query_payload = batch_items
    except Exception:
      pass

    # Fallback: If no JSON found, use the raw text
    if not query_payload:
      query_payload = [source_text.strip()]

    # *** CLEANING STEP ***
    # The client wraps items in a prompt (e.g., "Translate this... Text to translate:\nBCC").
    # We must strip this prefix to get the raw content for RAG and Logging.
    delimiter = "Text to translate:\n"
    cleaned_payload = []
    for item in query_payload:
      if delimiter in item:
        # Split by the delimiter and take the last part (the actual text)
        cleaned_payload.append(item.split(delimiter)[-1])
      else:
        cleaned_payload.append(item)

    query_payload = cleaned_payload

    # --- 3. RAG LOOKUP (Batched) ---
    expert_instructions = get_system_prompt_from_md()
    rag_content = ""

    # We use sets to avoid duplicate context entries
    found_glossary = set()
    found_tm = set()

    try:
      # A. Glossary Lookup
      gloss_col = chroma_client.get_collection("drupal_glossary")
      # Query with the LIST of strings. n_results=1 implies "Find the 1 best glossary term per string"
      gloss_res = gloss_col.query(query_texts = query_payload, n_results = 1)

      if gloss_res['documents']:
        # Iterate through the results for each string in the batch
        for i, doc_list in enumerate(gloss_res['documents']):
          if doc_list: # If a match was found for this specific string
             src = doc_list[0]
             tgt = gloss_res['metadatas'][i][0].get('target', '')
             # Create a unique key to prevent duplicates
             found_glossary.add(f"- '{src}' -> '{tgt}'")

      # B. TM Lookup
      tm_col = chroma_client.get_collection("drupal_tm")
      tm_res = tm_col.query(query_texts = query_payload, n_results = 1)

      if tm_res['documents']:
        for i, doc_list in enumerate(tm_res['documents']):
          if doc_list:
             src = doc_list[0]
             tgt = tm_res['metadatas'][i][0].get('target', '')
             # Only add if the TM match is somewhat similar (distance check could go here)
             found_tm.add(f"Source: {src}\nTarget: {tgt}")

    except Exception as e:
      print(f"⚠️ RAG Lookup skipped: {e}", flush = True)

    # Format the RAG content string
    if found_glossary:
      rag_content += "\n<glossary_matches>\n" + "\n".join(found_glossary) + "\n</glossary_matches>\n"

    if found_tm:
      rag_content += "\n<translation_memory_matches>\n" + "\n---\n".join(found_tm) + "\n</translation_memory_matches>\n"

    # --- 4. CONSTRUCT PROMPT ---
    original_system = data.get('system', "")
    if isinstance(original_system, list):
       original_system = " ".join([s.get('text', '') for s in original_system if 'text' in s])

    final_system = f"{expert_instructions}\n\n{rag_content}\n\n## Additional Instructions:\n{original_system}"

# --- 5. LOGGING ---
    print("\n" + "=" * 50, flush = True)
    print(f"--- REQUEST RECEIVED (Model: {requested_model}) ---", flush = True)

    if rag_content.strip():
      print(f"📚 RAG CONTEXT RETRIEVED ({len(found_glossary)} gloss, {len(found_tm)} TM):", flush = True)
      print(rag_content[:500] + ("..." if len(rag_content) > 500 else ""), flush = True)
    else:
      print("⚠️ NO RAG CONTEXT FOUND", flush = True)
    print("-" * 20, flush = True)

    print(f"📦 BATCH SIZE: {len(query_payload)} items", flush = True)
    # This line was missing in the previous version:
    print(json.dumps(query_payload, indent = 2, ensure_ascii = False), flush = True)

    print("=" * 50 + "\n", flush = True)

    # --- 6. DRY RUN CHECK ---
    # If the model `claude-opus-4-5-20251101` is specified, a dry run is triggered
    if requested_model == "claude-opus-4-5-20251101"":
      print(f"🚫 DRY RUN STOP: Aborting API call.", flush = True)
      mock_translations = [f"[DRY RUN] Translation {i + 1}" for i in range(len(query_payload))]

      return jsonify({
        "id": f"msg_dryrun_{int(time.time())}",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": json.dumps(mock_translations, ensure_ascii = False)}],
        "model": "dry-run-mock",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 0, "output_tokens": 0}
      })

    # --- 7. REAL API CALL ---
    response = real_claude.messages.create(
      model = requested_model,
      max_tokens = data.get('max_tokens', 1000),
      messages = messages,
      system = final_system,
      temperature = 0
    )
    return jsonify(response.model_dump())

  except Exception as e:
    print(f"❌ ERROR: {e}", flush = True)
    return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
  app.run(host = '0.0.0.0', port = 5000)
