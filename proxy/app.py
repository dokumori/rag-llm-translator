from flask import Flask, request, jsonify
import chromadb
import anthropic
import os

app = Flask(__name__)

# Clients
real_claude = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
chroma_client = chromadb.HttpClient(
    host = os.environ.get("CHROMA_HOST", "chroma"),
    port = int(os.environ.get("CHROMA_PORT", 8000))
)

def get_system_prompt_from_md():
    path = "/app/system_prompt.md"
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return "You are a professional translator."

@app.route('/v1/messages', methods=['POST'])
def handle_translation():
    try:
        data = request.json
        messages = data.get('messages', [])
        user_messages = [m for m in messages if m.get('role') == 'user']

        # Default to Haiku 3 if not provided, but respect the client's choice
        requested_model = data.get('model', "claude-3-haiku-20240307")

        # Validation / Ping Check
        if not user_messages:
            return jsonify(real_claude.messages.create(
                model = requested_model,
                max_tokens = 10,
                messages = [{"role": "user", "content": "Ping"}]
            ).model_dump())

        source_text = user_messages[-1].get('content', '')

        # 1. Load Prompt
        expert_instructions = get_system_prompt_from_md()

        # 2. RAG Retrieval
        rag_content = ""
        try:
            # Check Glossary
            gloss_col = chroma_client.get_collection("drupal_glossary")
            gloss_res = gloss_col.query(query_texts=[source_text], n_results=5)
            if gloss_res['documents'] and gloss_res['documents'][0]:
                rag_content += "\n<glossary_matches>\n"
                for i, doc in enumerate(gloss_res['documents'][0]):
                    target = gloss_res['metadatas'][0][i].get('target', '')
                    rag_content += f"- '{doc}' -> '{target}'\n"
                rag_content += "</glossary_matches>\n"

            # Check TM
            tm_col = chroma_client.get_collection("drupal_tm")
            tm_res = tm_col.query(query_texts=[source_text], n_results=3)
            if tm_res['documents'] and tm_res['documents'][0]:
                rag_content += "\n<translation_memory_matches>\n"
                for i, doc in enumerate(tm_res['documents'][0]):
                    target = tm_res['metadatas'][0][i].get('target', '')
                    rag_content += f"Source: {doc}\nTarget: {target}\n---\n"
                rag_content += "</translation_memory_matches>\n"

        except Exception as e:
            print(f"⚠️ RAG Lookup skipped: {e}", flush=True)

        # 3. Construct Final Prompt
        original_system = data.get('system', "")
        if isinstance(original_system, list):
             original_system = " ".join([s.get('text', '') for s in original_system if 'text' in s])

        final_system = f"{expert_instructions}\n\n{rag_content}\n\n## Additional Instructions:\n{original_system}"

        # # 4. Log for Debugging
        # print("\n" + "="*50, flush=True)
        # print(f"--- SENDING PROMPT TO CLAUDE ({requested_model}) ---", flush=True)
        # print(f"SOURCE: {source_text[:50]}...", flush=True)
        # print("="*50 + "\n", flush=True)

        # 4. Log for Debugging
        print("\n" + "="*50, flush=True)
        print(f"--- SENDING PROMPT TO CLAUDE ({requested_model}) ---", flush=True)

        # ATTEMPT TO ISOLATE AND PRETTY-PRINT THE BATCH
        try:
            import json
            # The prompt usually ends with the JSON list. We look for the last opening bracket.
            # This avoids catching the "Example: [...]" inside the system instructions.
            list_start = source_text.rfind('[')

            if list_start != -1:
                json_part = source_text[list_start:]
                batch_items = json.loads(json_part)
                print(f"📦 BATCH CONTENT: {len(batch_items)} strings", flush=True)
                print(f"SOURCE: {source_text[:50]}...", flush=True)
                # ensure_ascii=False allows Japanese characters to print correctly
                print(json.dumps(batch_items, indent=2, ensure_ascii=False), flush=True)
            else:
                # Fallback: Print raw text if no JSON list found
                print(f"📜 FULL SOURCE TEXT (No JSON found):\n{source_text}", flush=True)

        except Exception as log_err:
            # If parsing fails, just print the raw text safely
            print(f"📜 RAW SOURCE TEXT (Parse failed: {log_err}):\n{source_text}", flush=True)

        print("="*50 + "\n", flush=True)

        # 5. Call API
        response = real_claude.messages.create(
            model = requested_model, # <--- THIS IS THE KEY CHANGE
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
