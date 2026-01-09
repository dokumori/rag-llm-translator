from flask import Flask, request, jsonify
import chromadb
from chromadb.utils import embedding_functions
from openai import OpenAI
import os
import json
import time
import datetime
import re

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

@app.route('/v1/models', methods = ['GET'])
def list_models():
  """
  Returns a static list of models to satisfy the gpt-po-translator validation check.
  Includes the special dry-run ID.
  """
  return jsonify({
    "object": "list",
    "data": [
      {"id": "deepseek-r1-v1", "object": "model", "owned_by": "amazee"},
      {"id": "claude-3-5-sonnet", "object": "model", "owned_by": "amazee"},
      {"id": "claude-opus-4-20250514-v1", "object": "model", "owned_by": "amazee"},
      {"id": "claude-sonnet-4-20250514-v1", "object": "model", "owned_by": "amazee"},
      {"id": "mistral-large-2402-v1", "object": "model", "owned_by": "amazee"},
      {"id": "claude-opus-4-5-20251101", "object": "model", "owned_by": "amazee"} # DRY RUN ID
    ]
  })

@app.route('/v1/chat/completions', methods = ['POST'])
def handle_translation():
  start_time = time.time()
  try:
    data = request.json
    messages = data.get('messages', [])
    requested_model = data.get('model', "deepseek-r1-v1").strip()

    # Initialize Structured Log
    log_entry = {
      "timestamp": datetime.datetime.utcnow().isoformat(),
      "model": requested_model,
      "rag_matches": [],
      "input_text": []
    }

    user_messages = [m for m in messages if m.get('role') == 'user']
    if not user_messages:
      return jsonify({"choices": [{"message": {"content": "Ping"}}]})

    source_text = user_messages[-1].get('content', '')

    # --- 1. EXTRACT CONTENT FOR RAG ---
    # REVISED: "Sliding Window" JSON Parsing.
    # Scans backwards for '[' and checks if a valid list starts there.
    # This correctly ignores brackets inside the text (e.g. [site:name]).
    query_payload = []
    
    start_indices = [i for i, char in enumerate(source_text) if char == '[']
    
    for idx in reversed(start_indices):
      try:
        # Check 1: Try parsing from this bracket to the very end
        candidate = source_text[idx:]
        parsed = json.loads(candidate)
        if isinstance(parsed, list):
          query_payload = parsed
          break
      except json.JSONDecodeError:
        # Check 2: Try parsing from this bracket to the last ']'
        try:
          last_bracket = source_text.rfind(']')
          if last_bracket > idx:
            candidate_trimmed = source_text[idx : last_bracket + 1]
            parsed = json.loads(candidate_trimmed)
            if isinstance(parsed, list):
              query_payload = parsed
              break
        except Exception:
          pass

    # Fallback: Treat as single item
    if not query_payload:
      query_payload = [source_text.strip()]

    delimiter = "Text to translate:\n"
    cleaned_payload = []
    for item in query_payload:
      if delimiter in item:
        cleaned_payload.append(item.split(delimiter)[-1])
      else:
        cleaned_payload.append(item)
    query_payload = cleaned_payload

    log_entry["input_text"] = query_payload
    log_entry["batch_size"] = len(query_payload)

    # --- 2. RAG LOOKUP CONFIG ---
    expert_instructions = get_system_prompt_from_md()
    rag_content = ""
    found_glossary = set()
    found_tm = set()

    # STRICT THRESHOLDS
    # Revised: Increased to account for asymmetric embedding distance floor (~0.15)
    TM_THRESHOLD = 0.23
    GLOSSARY_THRESHOLD = 0.25

    try:
      existing_collections = [c.name for c in chroma_client.list_collections()]

      # Prepare the E5 query prefix
      formatted_query = ["query: " + text for text in query_payload]

      if "drupal_glossary" in existing_collections:
        gloss_col = chroma_client.get_collection("drupal_glossary", embedding_function = e5_ef)
        gloss_res = gloss_col.query(query_texts = formatted_query, n_results = 1)
        if gloss_res['documents']:
          for i, doc_list in enumerate(gloss_res['documents']):
            if doc_list:
              dist = gloss_res['distances'][i][0]
              # Remove 'passage: ' prefix for logs and prompt
              src = doc_list[0].replace("passage: ", "")
              tgt = gloss_res['metadatas'][i][0].get('target', '')

              is_accepted = dist < GLOSSARY_THRESHOLD
              log_entry["rag_matches"].append({
                "type": "glossary", "query": query_payload[i], "src": src, "tgt": tgt, "dist": dist, "accepted": is_accepted
              })

              if is_accepted:
                found_glossary.add(f"- '{src}' -> '{tgt}'")

      if "drupal_tm" in existing_collections:
        tm_col = chroma_client.get_collection("drupal_tm", embedding_function = e5_ef)
        tm_res = tm_col.query(query_texts = formatted_query, n_results = 1)
        if tm_res['documents']:
          for i, doc_list in enumerate(tm_res['documents']):
            if doc_list:
              dist = tm_res['distances'][i][0]
              src = doc_list[0].replace("passage: ", "")
              tgt = tm_res['metadatas'][i][0].get('target', '')

              is_accepted = dist < TM_THRESHOLD
              log_entry["rag_matches"].append({
                "type": "tm", "query": query_payload[i], "src": src, "tgt": tgt, "dist": dist, "accepted": is_accepted
              })

              if is_accepted:
                found_tm.add(f"Source: {src}\nTarget: {tgt}")

    except Exception as e:
      log_entry["rag_error"] = str(e)
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

    # --- 4. STRUCTURED LOGGING ---
    log_entry["system_prompt_length"] = len(final_system_content)
    print(json.dumps(log_entry, ensure_ascii = False), flush = True)

    # --- 5. DRY RUN CHECK ---
    if requested_model == "claude-opus-4-5-20251101":
      log_entry["action"] = "dry_run"
      mock_translations = [f"[DRY RUN] {item}" for item in query_payload]
      content_return = json.dumps(mock_translations, ensure_ascii = False)
      return jsonify({
        "id": "dry-run",
        "object": "chat.completion",
        "choices": [{
          "index": 0,
          "message": {"role": "assistant", "content": content_return},
          "finish_reason": "stop"
        }]
      })

    # --- 6. REAL API CALL ---
    new_messages = [{"role": "system", "content": final_system_content}]
    new_messages += [m for m in messages if m.get('role') != 'system']

    response = upstream_client.chat.completions.create(
      model = requested_model,
      messages = new_messages,
      temperature = 0,
      max_tokens = data.get('max_tokens', 1000)
    )

    log_entry["processing_time"] = time.time() - start_time
    return jsonify(response.model_dump())

  except Exception as e:
    print(f"❌ ERROR: {e}", flush = True)
    return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
  app.run(host = '0.0.0.0', port = 5000)
