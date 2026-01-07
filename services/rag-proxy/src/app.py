from flask import Flask, request, jsonify
import chromadb
from chromadb.utils import embedding_functions
import anthropic
import os
import sys
import json
import time
app = Flask(__name__)

# --- 1. Load Model at Startup (Prevent Timeout on first request) ---
print("⏳ Loading Embedding Model... (This may take a while)", flush=True)
e5_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
  model_name="intfloat/multilingual-e5-large" # consider 'small' if OOM occurs
)
print("✅ Embedding Model Loaded", flush=True)

# Clients
real_claude = anthropic.Anthropic(api_key = os.environ.get("ANTHROPIC_API_KEY"))
chroma_client = chromadb.HttpClient(
  host = os.environ.get("CHROMA_HOST", "chroma"),
  port = int(os.environ.get("CHROMA_PORT", 8000))
)

# --- Define the E5 Embedding Function ---
e5_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
  model_name = "intfloat/multilingual-e5-large"
)

def get_system_prompt_from_md():
  # MATCHES VOLUME: ./config/system_prompt.md:/app/system_prompt.md:ro
  path = "/app/system_prompt.md"
  if os.path.exists(path):
    with open(path, "r", encoding = "utf-8") as f:
      return f.read()
  return "You are a professional translator."

# --- NEW ROUTE: Mock Model List ---
@app.route('/v1/models', methods = ['GET'])
def list_models():
  return jsonify({
    "data": [
      {"id": "claude-3-haiku-20240307", "type": "model"},
      {"id": "claude-3-sonnet-20240229", "type": "model"},
      {"id": "claude-opus-4-5-20251101", "type": "model"}, 
      {"id": "claude-haiku-4-5-20251001", "type": "model"},
      {"id": "claude-sonnet-4-5-20250929", "type": "model"},
      {"id": "claude-3-opus-20240229", "type": "model"}
    ],
    "has_more": False,
    "first_id": "claude-3-haiku-20240307",
    "last_id": "claude-3-opus-20240229"
  })

@app.route('/v1/messages', methods = ['POST'])
def handle_translation():
  try:
    data = request.json
    messages = data.get('messages', [])
    user_messages = [m for m in messages if m.get('role') == 'user']

    # DEBUG: Strip whitespace to be safe
    requested_model = data.get('model', "claude-3-haiku-20240307").strip()

    # --- 1. VALIDATION / PING CHECK ---
    if not user_messages:
      return jsonify(real_claude.messages.create(
        model = "claude-3-haiku-20240307",
        max_tokens = 10,
        messages = [{"role": "user", "content": "Ping"}]
      ).model_dump())

    source_text = user_messages[-1].get('content', '')

    # --- 2. EXTRACT CONTENT FOR RAG ---
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

    if not query_payload:
      query_payload = [source_text.strip()]

    # *** CLEANING STEP ***
    delimiter = "Text to translate:\n"
    cleaned_payload = []
    for item in query_payload:
      if delimiter in item:
        cleaned_payload.append(item.split(delimiter)[-1])
      else:
        cleaned_payload.append(item)
    query_payload = cleaned_payload

    # --- 3. RAG LOOKUP (Batched) ---
    expert_instructions = get_system_prompt_from_md()
    rag_content = ""
    found_glossary = set()
    found_tm = set()
    
    # Set this high temporarily to ensure we see EVERYTHING in the logs
    SIMILARITY_THRESHOLD = 2.0 

    try:
      existing_collections = [c.name for c in chroma_client.list_collections()]

      # A. Glossary Lookup
      if "drupal_glossary" in existing_collections:
        gloss_col = chroma_client.get_collection("drupal_glossary", embedding_function=e5_ef)
        gloss_res = gloss_col.query(
          query_texts=query_payload, n_results=1, include=["documents", "metadatas", "distances"]
        )
        if gloss_res['documents']:
          for i, doc_list in enumerate(gloss_res['documents']):
            if doc_list:
               dist = gloss_res['distances'][i][0]
               src = doc_list[0]
               tgt = gloss_res['metadatas'][i][0].get('target', '')
               
               # LOG THE RAW DISTANCE
               print(f"📏 GLOSSARY DISTANCE: {dist:.4f} | Query: '{query_payload[i]}' vs Match: '{src}'", flush=True)

               if dist < SIMILARITY_THRESHOLD:
                 found_glossary.add(f"- '{src}' -> '{tgt}'")

      # B. TM Lookup
      if "drupal_tm" in existing_collections:
        tm_col = chroma_client.get_collection("drupal_tm", embedding_function=e5_ef)
        tm_res = tm_col.query(
          query_texts=query_payload, n_results=1, include=["documents", "metadatas", "distances"]
        )
        if tm_res['documents']:
          for i, doc_list in enumerate(tm_res['documents']):
            if doc_list:
               dist = tm_res['distances'][i][0]
               src = doc_list[0]
               tgt = tm_res['metadatas'][i][0].get('target', '')

               # LOG THE RAW DISTANCE
               print(f"📏 TM DISTANCE: {dist:.4f} | Query: '{query_payload[i]}' vs Match: '{src}'", flush=True)

               if dist < SIMILARITY_THRESHOLD:
                 found_tm.add(f"Source: {src}\nTarget: {tgt}")

    except Exception as e:
      print(f"⚠️ RAG Lookup skipped: {e}", flush=True)

    if found_glossary:
        rag_content += "\n<glossary_matches>\n" + "\n".join(found_glossary) + "\n</glossary_matches>\n"

    if found_tm:
        rag_content += "\n<tm_matches>\n" + "\n".join(found_tm) + "\n</tm_matches>\n"

    # --- 4. CONSTRUCT PROMPT ---
    original_system = data.get('system', "")
    if isinstance(original_system, list):
       original_system = " ".join([s.get('text', '') for s in original_system if 'text' in s])

    final_system = f"{expert_instructions}\n\n{rag_content}\n\n## Additional Instructions:\n{original_system}"

    # --- 5. LOGGING ---
    print("\n" + "=" * 50, flush = True)
    # DEBUG: Use repr() to reveal hidden characters
    print(f"--- REQUEST RECEIVED (Model: {repr(requested_model)}) ---", flush = True)

    if rag_content.strip():
      print(f"📚 RAG CONTEXT RETRIEVED ({len(found_glossary)} gloss, {len(found_tm)} TM):", flush = True)
      print(rag_content[:500] + ("..." if len(rag_content) > 500 else ""), flush = True)

    else:
      print("⚠️ NO RAG CONTEXT FOUND", flush = True)

    print("-" * 20, flush = True)
    print(f"📦 BATCH SIZE: {len(query_payload)} items", flush = True)
    print(json.dumps(query_payload, indent = 2, ensure_ascii = False), flush = True)
    print("=" * 50 + "\n", flush = True)

    # --- 6. DRY RUN CHECK ---
    # We now check with .strip() applied implicitly above
    if requested_model == "claude-opus-4-5-20251101":
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
    print(f"📡 SENDING REAL API CALL TO ANTHROPIC ({requested_model})...", flush = True)
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
