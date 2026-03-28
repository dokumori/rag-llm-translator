from flask import Flask, request, jsonify, Response
from openai import OpenAI
import os
import json
import time
import datetime
import re
from typing import List, Dict, Any, Tuple, Optional, Union
import logging
import functools
import snowballstemmer
from core.config import Config, load_models_config

# Initialize stemmer globally
_stemmer = snowballstemmer.stemmer('english')

# --- Logging Configuration ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    level=logging.INFO
)
# Silence chatty libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("chromadb").setLevel(logging.WARNING)
logging.getLogger("werkzeug").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

app = Flask(__name__)

from infrastructure import get_chroma_client, get_embedding_function

# --- Clients (Lazy & Cached) ---
_upstream_client = None


def get_upstream_client() -> OpenAI:
    """Returns a cached instance of the OpenAI client."""
    global _upstream_client
    if _upstream_client is None:
        _upstream_client = OpenAI(
            api_key=Config.LLM_API_TOKEN,
            base_url=Config.LLM_BASE_URL
        )
    return _upstream_client


# --- Configuration Paths ---
DEFAULT_LANG = Config.TARGET_LANG

@functools.lru_cache(maxsize=32)
def get_system_prompt_from_md(target_lang: str = DEFAULT_LANG) -> str:
    """
    Retrieves the expert system prompt dynamically based on the target language.
    Priority:
    1. Custom Override: /app/config/prompts/custom/{lang}.md
    2. Language Default: /app/config/prompts/{lang}.md
    3. Global Fallback: /app/config/prompts/generic.md
    """
    paths_to_check = [
        os.path.join(Config.PROMPTS_DIR, "custom", f"{target_lang}.md"),
        os.path.join(Config.PROMPTS_DIR, f"{target_lang}.md"),
        os.path.join(Config.PROMPTS_DIR, "generic.md")
    ]

    for path in paths_to_check:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        logger.info(f"📄 Loaded system prompt from: {path}")
                        return content
            except Exception as e:
                logger.error(f"❌ Failed to read prompt file {path}: {e}")

    logger.warning("⚠️ No system prompt found! Using hardcoded fallback.")
    return "Ensure the translation sounds natural and professional in the target language. Adhere to Microsoft Localization Style Guide."

@functools.lru_cache(maxsize=1)
def get_models_config() -> List[Dict[str, Any]]:
    """
    Retrieves model configurations from the shared JSON file, with custom override support.
    Uses load_models_config() to merge config/models/models.json with config/models/custom/models.json.
    """
    return load_models_config()


# Log configuration at startup
Config.log_config()

# --- Helper Functions ---

def parse_input_payload(source_text: str) -> List[str]:
    """
    Extracts the content to be translated using the 'Sliding Window' JSON parsing logic.
    Returns a cleaned list of strings.
    """
    query_payload: List[str] = []
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
                    candidate_trimmed = source_text[idx: last_bracket + 1]
                    parsed = json.loads(candidate_trimmed)
                    if isinstance(parsed, list):
                        query_payload = parsed
                        break
            except Exception:
                pass

    # Fallback: Treat as single item if no JSON list was identified
    if not query_payload:
        query_payload = [source_text.strip()]

    # Clean the content by removing the "Text to translate:\n" prefix if present
    delimiter = "Text to translate:\n"
    cleaned_payload: List[str] = []
    for item in query_payload:
        if isinstance(item, str) and delimiter in item:
            cleaned_payload.append(item.split(delimiter)[-1])
        else:
            cleaned_payload.append(item)

    return cleaned_payload

def simple_stem(word: str) -> str:
    """Stems an English word using the Snowball (Porter2) algorithm."""
    return _stemmer.stemWord(word)

# Minimal stop words list to prevent TM guardrail bypass
STOP_WORDS = {
    "a", "an", "the", "and", "but", "or", "for", "nor", "on", "at", "to", "from", 
    "by", "with", "of", "in", "is", "are", "was", "were", "be", "been", "being",
    "it", "this", "that", "these", "those", "we", "you", "they", "he", "she", "as"
}

def has_shared_stems(text_a: str, text_b: str) -> bool:
    """
    Checks whether two strings share at least one meaningful word stem,
    ignoring common stop words.
    """
    words_a = {w for w in re.findall(r'\w+', text_a.lower()) if w not in STOP_WORDS}
    words_b = {w for w in re.findall(r'\w+', text_b.lower()) if w not in STOP_WORDS}

    if not words_a or not words_b:
        return False

    # Fast path: exact word match
    if words_a.intersection(words_b):
        return True

    # Slow path: compare stems
    stems_a = {simple_stem(w) for w in words_a}
    stems_b = {simple_stem(w) for w in words_b}
    
    return len(stems_a.intersection(stems_b)) > 0




def perform_rag_lookup(query_payload: List[str]) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Queries ChromaDB, applies Guardrail logic (Glossary/TM), and returns
    the XML formatted context string and the list of match logs.
    """
    rag_content = ""
    matches_log: List[Dict[str, Any]] = []
    found_glossary: set = set()
    found_tm: set = set()

    # STRICT THRESHOLDS (Tuned for multilingual-e5-large)
    TM_THRESHOLD = Config.TM_THRESHOLD
    GLOSSARY_THRESHOLD = Config.GLOSSARY_THRESHOLD
    RAG_STRICT_DISTANCE_THRESHOLD = Config.RAG_STRICT_DISTANCE_THRESHOLD
    GLOSSARY_COLLECTION = Config.GLOSSARY_COLLECTION
    TM_COLLECTION = Config.TM_COLLECTION

    try:
        client = get_chroma_client()
        existing_collections = [c.name for c in client.list_collections()]

        # Prepare the E5 query prefix and strip whitespace
        formatted_query = ["query: " + text.strip() for text in query_payload]

        # Process Glossary
        if GLOSSARY_COLLECTION in existing_collections:
            gloss_col = client.get_collection(
                GLOSSARY_COLLECTION,
                embedding_function=get_embedding_function()
            )
            gloss_res = gloss_col.query(
                query_texts=formatted_query, n_results=1)
            if gloss_res['documents']:
                for i, doc_list in enumerate(gloss_res['documents']):
                    if doc_list:
                        dist = gloss_res['distances'][i][0]
                        src = doc_list[0].replace("passage: ", "")
                        tgt = gloss_res['metadatas'][i][0].get('target', '')

                        # --- GUARDRAIL (GLOSSARY) ---
                        is_semantic_match = dist < GLOSSARY_THRESHOLD
                        has_shared_words = has_shared_stems(query_payload[i], src)

                        # Reject if no shared words unless distance is extremely low (synonym exception)
                        if not has_shared_words and dist > RAG_STRICT_DISTANCE_THRESHOLD:
                            is_accepted = False
                            logger.info(
                                f"   🛡️ Glossary Guardrail Rejection: '{query_payload[i]}' vs '{src}' (Dist: {dist:.4f}, No shared words)")
                        else:
                            is_accepted = is_semantic_match

                        matches_log.append({
                            "type": "glossary", "query": query_payload[i], "src": src, "tgt": tgt, "dist": dist, "accepted": is_accepted
                        })

                        if is_accepted:
                            found_glossary.add(f"- '{src}' -> '{tgt}'")

        # Process Translation Memory (TM)
        if TM_COLLECTION in existing_collections:
            tm_col = client.get_collection(
                TM_COLLECTION,
                embedding_function=get_embedding_function()
            )
            tm_res = tm_col.query(query_texts=formatted_query, n_results=1)
            if tm_res['documents']:
                for i, doc_list in enumerate(tm_res['documents']):
                    if doc_list:
                        dist = tm_res['distances'][i][0]
                        src = doc_list[0].replace("passage: ", "")
                        tgt = tm_res['metadatas'][i][0].get('target', '')

                        # --- GUARDRAIL (TM) ---
                        is_semantic_match = dist < TM_THRESHOLD
                        has_shared_words = has_shared_stems(query_payload[i], src)

                        if not has_shared_words and dist > RAG_STRICT_DISTANCE_THRESHOLD:
                            is_accepted = False
                            logger.info(
                                f"   🛡️ TM Guardrail Rejection: '{query_payload[i]}' vs '{src}' (Dist: {dist:.4f}, No shared words)")
                        else:
                            is_accepted = is_semantic_match

                        matches_log.append({
                            "type": "tm", "query": query_payload[i], "src": src, "tgt": tgt, "dist": dist, "accepted": is_accepted
                        })

                        if is_accepted:
                            found_tm.add(f"Source: {src}\nTarget: {tgt}")

    except Exception as e:
        logger.error(f"⚠️ RAG Lookup skipped: {e}", exc_info=True)

    if found_glossary:
        rag_content += "\n<glossary_matches>\n" + \
            "\n".join(found_glossary) + "\n</glossary_matches>\n"
    if found_tm:
        rag_content += "\n<tm_matches>\n" + \
            "\n".join(found_tm) + "\n</tm_matches>\n"

    return rag_content, matches_log


def construct_system_prompt(original_system_data: Union[str, List[Dict[str, str]]], rag_content: str, target_lang: str) -> str:
    """Combines instructions, RAG context, and original system message."""
    expert_instructions = get_system_prompt_from_md(target_lang)

    original_system = original_system_data
    if isinstance(original_system, list):
        original_system = " ".join([s.get('text', '')
                                   for s in original_system if 'text' in s])

    return f"{expert_instructions}\n\n{rag_content}\n\n## Additional Instructions:\n{original_system}"

# --- Routes ---

@app.route('/v1/models', methods=['GET'])
@app.route('/v1/skip_rag/models', methods=['GET'])
def list_models() -> Response:
    """Returns a dynamic list of models from configuration."""
    config_models = get_models_config()
    return jsonify({
        "object": "list",
        "data": [
            {"id": m["id"], "object": "model", "owned_by": "llm-provider"}
            for m in config_models
        ]
    })


@app.route('/v1/chat/completions', methods=['POST'])
@app.route('/v1/skip_rag/chat/completions', methods=['POST'])
def handle_translation() -> Union[Response, Tuple[Response, int]]:
    """Main endpoint for handling translation requests."""
    start_time = time.time()
    try:
        data = request.json
        messages = data.get('messages', [])
        requested_model = (data.get('model') or "claude-opus-4-5-20251101").strip()

        log_entry: Dict[str, Any] = {
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
        query_payload = parse_input_payload(source_text)
        log_entry["input_text"] = query_payload
        log_entry["batch_size"] = len(query_payload)

        # --- 2. RAG LOOKUP ---
        skip_rag = 'skip_rag' in request.path or str(request.args.get('skip_rag', '')).lower() == 'true'
        rag_content = ""
        rag_matches = []
        
        if not skip_rag:
            try:
                rag_content, rag_matches = perform_rag_lookup(query_payload)
                log_entry["rag_matches"] = rag_matches
            except Exception as e:
                log_entry["rag_error"] = str(e)
                logger.error(f"⚠️ RAG Lookup skipped: {e}", exc_info=True)
                # Non-critical, we proceed without RAG
        else:
            logger.info("⏩ Skipping RAG lookup as requested (`skip_rag` is true)")
            rag_content = "\n<!-- RAG Lookup Skipped -->\n"

        # --- 3. CONSTRUCT PROMPT ---
        target_lang = data.get('target_lang') or request.headers.get('X-Target-Lang') or DEFAULT_LANG
        final_system_content = construct_system_prompt(
            data.get('system', ""), rag_content, target_lang)

        # --- 4. STRUCTURED LOGGING ---
        log_entry["system_prompt_length"] = len(final_system_content)
        logger.info(json.dumps(log_entry, ensure_ascii=False))

        # --- 4a. PREPARE PAYLOAD ---
        new_messages = [{"role": "system", "content": final_system_content}]
        new_messages += [m for m in messages if m.get('role') != 'system']

        logger.info(f"FINAL_PAYLOAD: {json.dumps({'model': requested_model, 'messages': new_messages}, ensure_ascii=False)}")

        # --- 5. DRY RUN CHECK ---
        model_meta = next((m for m in get_models_config()
                          if m["id"] == requested_model), None)
                          
        # Force dry run if:
        #   - the model is marked as dry_run
        #   - the model is not given
        #   - entirely unknown
        is_dry_run = model_meta.get("is_dry_run") if model_meta else True

        if is_dry_run:
            log_entry["action"] = "dry_run"
            mock_translations = [f"[DRY RUN] {item}" for item in query_payload]
            content_return = json.dumps(mock_translations, ensure_ascii=False)
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

        try:
            response = get_upstream_client().chat.completions.create(
                model=requested_model,
                messages=new_messages,
                temperature=0,
                max_tokens=data.get('max_tokens', 1000)
            )
            
            # --- API ERROR CHECKS ---
            for choice in response.choices:
                if choice.finish_reason in ["safety", "content_filter"]:
                    logger.warning(f"🚨 GUARDRAIL BLOCKED TRANSLATION! Finish Reason: {choice.finish_reason}")
                elif not choice.message.content:
                    logger.warning(f"🚨 LLM RETURNED EMPTY STRING! Finish Reason: {choice.finish_reason}")
            
            raw_content = response.choices[0].message.content or ""
            sneak_peek = raw_content[:150].strip().replace('\n', ' ')
            logger.info(f"raw_output_sneak_peek: {sneak_peek}")
            # -----------------------------

            log_entry["processing_time"] = time.time() - start_time
            return jsonify(response.model_dump())
        except Exception as e:
            if hasattr(e, 'response'):
                code = getattr(e.response, 'status_code', 'Unknown')
                text = getattr(e.response, 'text', 'Unknown')
                logger.error(f"❌ API Error Code: {code}")
                logger.error(f"❌ API Error Body: {text}")
            logger.error(f"❌ Translation provider error: {e}", exc_info=True)
            return jsonify({"error": "Translation provider unavailable"}), 502

    except Exception as e:
        logger.error(f"❌ ERROR: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check() -> Tuple[Response, int]:
    """
    Healthz endpoint for Docker and Load Balancers.
    Checks connectivity to Vector Database.
    """
    try:
        client = get_chroma_client()
        client.heartbeat()
        return jsonify({"status": "ok", "database": "connected"}), 200
    except Exception as e:
        logger.error(f"❌ Health check failed: {e}", exc_info=True)
        return jsonify({"status": "error", "database": "disconnected", "details": str(e)}), 503


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
