from flask import Flask, request, jsonify
import chromadb
from chromadb.utils import embedding_functions
from openai import OpenAI
import os
import json
import time

app = Flask(__name__)

# --- 1. Load Model at Startup ---
print("⏳ Loading Embedding Model...", flush = True)
e5_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
  model_name = "intfloat/multilingual-e5-large"
)
print("✅ Embedding Model Loaded", flush = True)

# --- 2. Clients ---
amazee_api_key = os.environ.get("AMAZEE_API_KEY")
amazee_base_url = "https://llm.us104.amazee.ai/v1"

upstream_client = OpenAI(
  api_key = amazee_api_key,
  base_url = amazee_base_url
)

chroma_client = chromadb.HttpClient(
  host = os.environ.get("CHROMA_HOST", "chroma"),
  port = int(os.environ.get("CHROMA_PORT", 8000))
)

def get_system_prompt_from_md():
  path = "/app/system_prompt.md"
  if os.path.exists(path):
    with open(path, "r", encoding = "utf-8") as f:
      content = f.read().strip()
      if content:
        return content
  return "You are a professional translator for Drupal CMS."

@app.route('/v1/chat/completions', methods = ['POST'])
def handle_translation():
  try:
    data = request.json
    messages = data.get('messages', [])
    requested_model = data.get('model', "deepseek-r1-v1").strip()

    user_messages = [m for m in messages if m.get('role') == 'user']
    if not user_messages:
      return jsonify({"choices": [{"message": {"content": "Ping"}}]})

    source_text = user_messages[-1].get('content', '')

    # --- 1. EXTRACT CONTENT FOR RAG (RESTORED) ---
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

    # Cleaning step
    delimiter = "Text to translate:\n"
    cleaned_payload = []
    for item in query_payload:
      if delimiter in item:
        cleaned_payload.append(item.split(delimiter)[-1])
      else:
        cleaned_payload.append(item)
    query_payload = cleaned_payload

    # --- 2. RAG LOOKUP (RESTORED) ---
    expert_instructions = get_system_prompt_from_md()
    rag_content = ""
    found_glossary = set()
    found_tm = set()
    SIMILARITY_THRESHOLD = 2.0

    try:
      existing_collections = [c.name for c in chroma_client.list_collections()]

      if "drupal_glossary" in existing_collections:
        gloss_col = chroma_client.get_collection("drupal_glossary", embedding_function = e5_ef)
        gloss_res = gloss_col.query(query_texts = query_payload, n_results = 1)
        if gloss_res['documents']:
          for i, doc_list in enumerate(gloss_res['documents']):
            if doc_list:
              dist = gloss_res['distances'][i][0]
              src = doc_list[0]
              tgt = gloss_res['metadatas'][i][0].get('target', '')
              print(f"📏 GLOSSARY DISTANCE: {dist:.4f} | Query: '{query_payload[i][:30]}...' vs Match: '{src[:30]}...'", flush = True)
              if dist < SIMILARITY_THRESHOLD:
                found_glossary.add(f"- '{src}' -> '{tgt}'")

      if "drupal_tm" in existing_collections:
        tm_col = chroma_client.get_collection("drupal_tm", embedding_function = e5_ef)
        tm_res = tm_col.query(query_texts = query_payload, n_results = 1)
        if tm_res['documents']:
          for i, doc_list in enumerate(tm_res['documents']):
            if doc_list:
              dist = tm_res['distances'][i][0]
              src = doc_list[0]
              tgt = tm_res['metadatas'][i][0].get('target', '')
              print(f"📏 TM DISTANCE: {dist:.4f} | Query: '{query_payload[i][:30]}...' vs Match: '{src[:30]}...'", flush = True)
              if dist < SIMILARITY_THRESHOLD:
                found_tm.add(f"Source: {src}\nTarget: {tgt}")

    except Exception as e:
      print(f"⚠️ RAG Lookup skipped: {e}", flush = True)

    if found_glossary:
      rag_content += "\n<glossary_matches>\n" + "\n".join(found_glossary) + "\n</glossary_matches>\n"
    if found_tm:
      rag_content += "\n<tm_matches>\n" + "\n".join(found_tm) + "\n</tm_matches>\n"

    # --- 3. CONSTRUCT PROMPT ---
    original_system = data.get('system', "")
    if isinstance(original_system, list):
      original_system = " ".join([s.get('text', '') for s in original_system if 'text' in s])

    final_system_content = f"{expert_instructions}\n\n{rag_content}\n\n## Additional Instructions:\n{original_system}"

    # --- 4. LOGGING (RESTORED) ---
    print("\n" + "=" * 50, flush = True)
    print(f"--- REQUEST RECEIVED (Model: {repr(requested_model)}) ---", flush = True)

    if rag_content.strip():
      print(f"📚 RAG CONTEXT RETRIEVED ({len(found_glossary)} gloss, {len(found_tm)} TM):", flush = True)
      # print(rag_content[:500] + ("..." if len(rag_content) > 500 else ""), flush = True)
    else:
      print("⚠️ NO RAG CONTEXT FOUND", flush = True)

    print("-" * 20, flush = True)
    print(f"📦 BATCH SIZE: {len(query_payload)} items", flush = True)
    print("=" * 50 + "\n", flush = True)

    # --- 5. DRY RUN CHECK ---
    if requested_model == "claude-opus-4-5-20251101":
      print(f"🚫 DRY RUN STOP: Aborting API call.", flush = True)
      mock_translations = [f"[DRY RUN] {item}" for item in query_payload]
      # Return valid OpenAI JSON structure
      content_str = json.dumps(mock_translations, ensure_ascii = False)
      return jsonify({
        "id": "dry-run",
        "object": "chat.completion",
        "choices": [{
          "index": 0,
          "message": {"role": "assistant", "content": json.dumps(mock_translations, ensure_ascii = False)},
          # "message": {"role": "assistant", "content": content_str},
          "finish_reason": "stop"
        }]
      })

    # --- 6. REAL API CALL ---
    new_messages = [{"role": "system", "content": final_system_content}]
    new_messages += [m for m in messages if m.get('role') != 'system']

    print(f"📡 SENDING REAL API CALL TO AMAZEE ({requested_model})...", flush = True)
    response = upstream_client.chat.completions.create(
      model = requested_model,
      messages = new_messages,
      temperature = 0,
      max_tokens = data.get('max_tokens', 1000)
    )
    return jsonify(response.model_dump())

  except Exception as e:
    print(f"❌ ERROR: {e}", flush = True)
    return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
  app.run(host = '0.0.0.0', port = 5000)
